import io
import os
import subprocess
import sys

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.deletion import ProtectedError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image as PILImage
from wagtail.admin.panels import get_edit_handler
from wagtail.images import get_image_model
from wagtail.models import Page, Site

from adventures.models import AdventureIndexPage, AdventurePage, AdventureRoute, Route, Waypoint, WaypointPhoto
from adventures.tests import GPX
from adventures.views import waypoint_manifest


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class WaypointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        root = Page.objects.get(depth=1)
        Site.objects.update(root_page=root)
        index = root.add_child(instance=AdventureIndexPage(title='Adventures', slug='adventures'))
        cls.page = index.add_child(instance=AdventurePage(title='Trip', slug='trip', live=False))
        cls.admin = get_user_model().objects.create_superuser('stops', 'stops@example.com', 'password')

    def route(self, public=False, parent=None, mode='cycling'):
        return Route.objects.create(name='A recording', activity_type=mode, parent_route=parent,
                                    file=SimpleUploadedFile('leg.gpx', GPX), is_public=public)

    def image(self, title='Photo'):
        data = io.BytesIO()
        PILImage.new('RGB', (20, 20), '#a8532e').save(data, format='PNG')
        return get_image_model().objects.create(title=title, file=SimpleUploadedFile('photo.png', data.getvalue(), content_type='image/png'))

    def stop(self, route=None, public=False, latitude=40, longitude=-73):
        return Waypoint.objects.create(name='A stop', latitude=latitude, longitude=longitude,
                                       route=route, is_public=public)

    def form(self, *, public=False, route=None, image=None, latitude='40', longitude='-73'):
        data = {
            'name': 'A stop', 'description': '', 'route': str(route.pk) if route else '',
            'latitude': latitude, 'longitude': longitude,
            'photos-TOTAL_FORMS': '1' if image else '0',
            'photos-INITIAL_FORMS': '0', 'photos-MIN_NUM_FORMS': '0', 'photos-MAX_NUM_FORMS': '1000',
        }
        if public:
            data['is_public'] = 'on'
        if image:
            data.update({'photos-0-image': str(image.pk), 'photos-0-caption': 'First', 'photos-0-ORDER': '0'})
        return get_edit_handler(Waypoint).get_form_class()(data=data, for_user=self.admin)

    def test_draft_form_can_save_without_route_or_photo_and_public_requires_both(self):
        draft = self.form()
        self.assertTrue(draft.is_valid(), draft.errors)
        draft.save()
        self.assertFalse(self.form(public=True).is_valid())
        route = self.route(public=True)
        no_photo = self.form(public=True, route=route, latitude='41')
        self.assertFalse(no_photo.is_valid())
        self.assertIn('is_public', no_photo.errors)
        image = self.image()
        ready = self.form(public=True, route=route, image=image, latitude='42')
        self.assertTrue(ready.is_valid(), ready.errors)
        stop = ready.save()
        self.assertEqual(list(stop.photos.values_list('image_id', flat=True)), [image.pk])

    def test_coordinate_and_route_validation(self):
        route = self.route(public=True)
        first = self.stop(route=route)
        with self.assertRaises(ValidationError):
            self.stop(latitude=first.latitude, longitude=first.longitude).full_clean()
        for latitude, longitude in [(91, 0), (0, -181)]:
            with self.assertRaises(ValidationError):
                Waypoint(name='Out of range', latitude=latitude, longitude=longitude).full_clean()
        group = Route.objects.create(name='Group', kind='group')
        child = self.route(parent=group)
        with self.assertRaises(ValidationError):
            Waypoint(name='Wrong route', latitude=41, longitude=-74, route=child).full_clean()
        self.assertNotIn(child, self.form().fields['route'].queryset)

    def test_manifest_and_detail_share_visibility_and_photo_order(self):
        route = self.route(public=True)
        stop = self.stop(route=route, public=True)
        first, second = self.image('First'), self.image('Second')
        WaypointPhoto.objects.create(waypoint=stop, image=second, sort_order=1, caption='Second caption')
        WaypointPhoto.objects.create(waypoint=stop, image=first, sort_order=0, caption='First caption')
        manifest = waypoint_manifest()
        self.assertEqual([item['id'] for item in manifest], [stop.pk])
        self.assertEqual(len(manifest[0]['previews']), 2)
        self.assertTrue(all('fill-120x150' in url for url in manifest[0]['previews']))
        for position in range(2, 6):
            WaypointPhoto.objects.create(waypoint=stop, image=first, sort_order=position)
        manifest = waypoint_manifest()
        self.assertEqual(manifest[0]['photo_count'], 6)
        self.assertEqual(len(manifest[0]['previews']), 5)
        response = self.client.get(reverse('adventure-waypoint-detail', args=[stop.pk]))
        self.assertEqual(response.status_code, 200)
        photos = response.json()['photos']
        self.assertEqual([item['caption'] for item in photos[:2]], ['First caption', 'Second caption'])
        self.assertEqual(len(photos), 6)
        self.assertTrue(all('width-1200' in item['url'] for item in photos))
        self.assertIn('map-waypoints', self.client.get('/').content.decode())
        stop.is_public = False
        stop.save()
        self.assertEqual(waypoint_manifest(), [])
        self.assertEqual(self.client.get(reverse('adventure-waypoint-detail', args=[stop.pk])).status_code, 404)
        stop.is_public = True
        stop.save()
        route.is_public = False
        route.save()
        self.assertEqual(waypoint_manifest(), [])
        self.assertEqual(self.client.get(reverse('adventure-waypoint-detail', args=[stop.pk])).status_code, 404)

    def test_group_visibility_and_mixed_activity(self):
        group = Route.objects.create(name='Mixed trip', kind='group', is_public=True)
        self.route(parent=group, mode='cycling')
        self.route(parent=group, mode='hiking')
        stop = self.stop(route=group, public=True)
        WaypointPhoto.objects.create(waypoint=stop, image=self.image())
        self.assertEqual(waypoint_manifest()[0]['route_id'], group.pk)
        from adventures.views import route_manifest
        request = self.client.request().wsgi_request
        group_item = next(item for item in route_manifest(request) if item['id'] == group.pk)
        self.assertEqual(set(group_item['activity_types']), {'cycling', 'hiking'})
        with self.assertRaises(ProtectedError):
            group.delete()

    def test_story_visible_route_and_hidden_child_do_not_leak(self):
        group = Route.objects.create(name='Private group', kind='group')
        child = self.route(parent=group)
        AdventureRoute.objects.create(page=self.page, route=group, sort_order=0)
        group_stop = self.stop(route=group, public=True)
        WaypointPhoto.objects.create(waypoint=group_stop, image=self.image())
        child_stop = self.stop(route=child, public=True, latitude=41, longitude=-74)
        WaypointPhoto.objects.create(waypoint=child_stop, image=self.image('Child'))
        self.assertEqual(waypoint_manifest(), [])
        self.page.save_revision().publish()
        self.assertEqual([item['id'] for item in waypoint_manifest()], [group_stop.pk])
        self.assertEqual(self.client.get(reverse('adventure-waypoint-detail', args=[child_stop.pk])).status_code, 404)
        group_stop.photos.all().delete()
        self.assertEqual(waypoint_manifest(), [])
        self.assertEqual(self.client.get(reverse('adventure-waypoint-detail', args=[group_stop.pk])).status_code, 404)

    def test_private_route_preview_needs_editor_permission(self):
        route = self.route()
        url = reverse('adventure-route-geojson', args=[route.pk]) + '?overview=1'
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)


class WaypointMigrationTests(SimpleTestCase):
    def test_current_and_revision_only_waypoints_survive_restore(self):
        script = r'''
import django
from django.conf import settings
settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
executor = MigrationExecutor(connection)
executor.migrate([('adventures', '0014_route_groups')])
old = executor.loader.project_state([('adventures', '0014_route_groups')]).apps
Adventure = old.get_model('adventures', 'AdventurePage')
Route = old.get_model('adventures', 'Route')
RouteLink = old.get_model('adventures', 'AdventureRoute')
Waypoint = old.get_model('adventures', 'Waypoint')
Revision = old.get_model('wagtailcore', 'Revision')
ContentType = old.get_model('contenttypes', 'ContentType')
ct, _ = ContentType.objects.get_or_create(app_label='adventures', model='adventurepage')
page = Adventure.objects.create(path='00010002', depth=2, numchild=0, title='Story', slug='story', locale_id=1, content_type_id=ct.pk)
group = Route.objects.create(name='Trip', kind='group')
RouteLink.objects.create(page=page, route=group, sort_order=0)
current = Waypoint.objects.create(page=page, name='Now', latitude=40, longitude=-73, sort_order=2)
other_page = Adventure.objects.create(path='00010003', depth=2, numchild=0, title='Ambiguous story', slug='ambiguous', locale_id=1, content_type_id=ct.pk)
other_route = Route.objects.create(name='Another recording', kind='recording')
RouteLink.objects.create(page=other_page, route=group, sort_order=0)
RouteLink.objects.create(page=other_page, route=other_route, sort_order=1)
ambiguous = Waypoint.objects.create(page=other_page, name='Needs route review', latitude=42, longitude=-75, sort_order=0)
content = {'pk': page.pk, 'page_ptr': page.pk, 'path': page.path, 'depth': 2, 'slug': page.slug,
           'title': page.title, 'locale': 1, 'content_type': ct.pk, 'body': '[]',
           'waypoints': [
               {'pk': current.pk, 'page': page.pk, 'name': 'Now', 'description': '', 'latitude': '40.000000', 'longitude': '-73.000000', 'sort_order': 2},
               {'pk': None, 'page': page.pk, 'name': 'Draft only', 'description': '', 'latitude': '41.000000', 'longitude': '-74.000000', 'sort_order': 3},
           ], 'adventure_routes': []}
revision = Revision.objects.create(created_at=timezone.now(), content_type_id=ct.pk, base_content_type_id=ct.pk,
                                    object_id=str(page.pk), content=content)
executor = MigrationExecutor(connection)
executor.migrate(executor.loader.graph.leaf_nodes())
from adventures.models import AdventurePage, AdventureWaypoint, Waypoint
from wagtail.models import Revision
assert Waypoint.objects.count() == 3
assert AdventureWaypoint.objects.count() == 2
assert Waypoint.objects.get(pk=current.pk).route_id == group.pk
assert Waypoint.objects.get(pk=ambiguous.pk).route_id is None
assert AdventureWaypoint.objects.get(page_id=page.pk).sort_order == 2
revision = Revision.objects.get(pk=revision.pk)
assert 'waypoints' not in revision.content
assert len(revision.content['adventure_waypoints']) == 2
restored = revision.as_object()
assert [link.waypoint.name for link in restored.adventure_waypoints.all()] == ['Now', 'Draft only']
restored.save_revision().publish()
assert AdventureWaypoint.objects.filter(page_id=page.pk).count() == 2
assert Waypoint.objects.count() == 3
'''
        result = subprocess.run([sys.executable, '-c', script], env={**os.environ, 'CARTO_API_KEY': os.environ.get('CARTO_API_KEY', '')}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
