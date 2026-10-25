from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from wagtail.admin.panels import get_edit_handler
from wagtail.models import Page, Site

from adventures.models import AdventureIndexPage, AdventurePage, AdventureRoute, Route
from adventures.tests import GPX
from adventures.views import public_routes


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'
        },
    }
)
class RouteGroupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        root = Page.objects.get(depth=1)
        Site.objects.update(root_page=root)
        cls.index = root.add_child(
            instance=AdventureIndexPage(title='Adventures', slug='adventures')
        )
        cls.page = cls.index.add_child(
            instance=AdventurePage(title='Journey story', slug='journey', live=False)
        )
        cls.admin = get_user_model().objects.create_superuser(
            'groups', 'groups@example.com', 'password'
        )

    def recording(
        self, name='Day one', mode='cycling', parent=None, position=0, **kwargs
    ):
        return Route.objects.create(
            name=name,
            activity_type=mode,
            parent_route=parent,
            position=position,
            file=SimpleUploadedFile('leg.gpx', GPX),
            **kwargs,
        )

    def group(self, **kwargs):
        return Route.objects.create(name='Taiwan trip', kind=Route.Kind.GROUP, **kwargs)

    def select(self, route, order=0):
        return AdventureRoute.objects.create(
            page=self.page, route=route, sort_order=order
        )

    def group_data(self, ids=(), **kwargs):
        data = {
            'kind': 'group',
            'name': 'Taiwan trip',
            'description': 'A trip in stages',
            'legs-TOTAL_FORMS': str(len(ids)),
            'legs-INITIAL_FORMS': '0',
            'legs-MIN_NUM_FORMS': '0',
            'legs-MAX_NUM_FORMS': '500',
        }
        for index, pk in enumerate(ids):
            data[f'legs-{index}-route'] = str(pk)
            data[f'legs-{index}-ORDER'] = str(index)
        return {**data, **kwargs}

    def form(self, data, instance=None, files=None):
        return get_edit_handler(Route).get_form_class()(
            data=data, files=files, instance=instance, for_user=self.admin
        )

    def test_group_derives_metadata_without_storing_copies(self):
        group = self.group()
        second = self.recording('Flight', 'flying', group, 1)
        first = self.recording('Ride', 'cycling', group, 0)
        group.refresh_from_db()
        self.assertEqual([r.pk for r in group.recordings], [first.pk, second.pk])
        self.assertEqual(group.activity_types, ['cycling', 'flying'])
        self.assertEqual(group.activity_label, 'Cycling / Flying')
        self.assertEqual(
            group.distance_km, round(first.distance_km + second.distance_km, 3)
        )
        self.assertEqual(group.stats['active_days'], 1)
        self.assertEqual(group.date_start, first.date_start)
        self.assertEqual(group.bounds, first.bounds)
        self.assertFalse(group.file)
        self.assertFalse(group.geojson_file)
        self.assertEqual(group.parsed_stats, {})
        self.assertEqual(group.activity_type, '')

    def test_selection_expands_groups_and_deduplicates_recordings(self):
        group = self.group()
        first = self.recording(parent=group)
        second = self.recording(name='Day two', parent=group, position=1)
        self.select(group)
        self.select(first, 1)
        page = AdventurePage.objects.get(pk=self.page.pk)
        self.assertEqual(
            [route.pk for route in page.selected_recordings], [first.pk, second.pk]
        )
        self.assertEqual(page.computed_stats['active_days'], 1)
        self.assertEqual(page.effective_distance_km, group.distance_km)
        context = page.get_context(None)
        self.assertEqual(len(context['route_urls']), 2)
        page.distance_km = 999
        self.assertEqual(page.computed_stats['distance_km'], group.distance_km)
        self.assertEqual(page.effective_distance_km, 999)

    def test_nested_groups_and_recording_parents_are_rejected(self):
        group = self.group()
        recording = self.recording()
        with self.assertRaises(ValidationError):
            Route(name='Nested', kind='group', parent_route=group).full_clean()
        recording.parent_route = recording
        with self.assertRaises(ValidationError):
            recording.save()
        recording.parent_route = self.recording(name='Wrong parent')
        with self.assertRaises(ValidationError):
            recording.full_clean()
        self.recording(parent=group)
        group.kind = 'recording'
        with self.assertRaises(ValidationError):
            group.save()

    def test_groups_and_attached_legs_cannot_be_deleted(self):
        group = self.group()
        child = self.recording(parent=group)
        for route in (group, child):
            with self.assertRaises(ProtectedError):
                route.delete()
        self.client.force_login(self.admin)
        response = self.client.post(
            f'/cms/snippets/adventures/route/delete/{child.pk}/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 403)

    def test_editor_selects_orders_and_detaches_without_reprocessing(self):
        first, second = self.recording(), self.recording(name='Day two')
        form = self.form(self.group_data([second.pk, first.pk]))
        self.assertTrue(form.is_valid(), form.errors)
        with patch('adventures.services.parse_route_file') as parser:
            group = form.save()
            parser.assert_not_called()
        self.assertEqual([r.pk for r in group.recordings], [second.pk, first.pk])
        form = self.form(self.group_data([first.pk]), instance=group)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        second.refresh_from_db()
        self.assertIsNone(second.parent_route_id)
        self.assertTrue(second.file)
        self.assertEqual(Route.objects.count(), 3)

    def test_detaching_clears_wagtail_usage_and_allows_empty_group_deletion(self):
        group = self.group()
        child = self.recording(parent=group)
        self.client.force_login(self.admin)
        form = self.form(self.group_data(), instance=group)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        response = self.client.post(
            f'/cms/snippets/adventures/route/delete/{group.pk}/'
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Route.objects.filter(pk=group.pk).exists())
        child.refresh_from_db()
        self.assertIsNone(child.parent_route_id)

    def test_bulk_delete_cannot_remove_a_grouped_recording(self):
        child = self.recording(parent=self.group())
        self.client.force_login(self.admin)
        url = reverse('wagtail_bulk_action', args=['adventures', 'route', 'delete'])
        response = self.client.post(
            f'{url}?id={child.pk}', HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Route.objects.filter(pk=child.pk).exists())

    def test_editor_uploads_new_leg_with_recording_metadata(self):
        data = self.group_data([None])
        data.update(
            {
                'legs-0-route': '',
                'legs-0-name': 'Uploaded leg',
                'legs-0-activity_type': 'flying',
            }
        )
        form = self.form(
            data, files={'legs-0-file': SimpleUploadedFile('new.gpx', GPX)}
        )
        self.assertTrue(form.is_valid(), (form.errors, form.legs.errors))
        group = form.save()
        child = group.children.get()
        self.assertTrue(child.geojson_file)
        self.assertEqual(child.activity_type, 'flying')
        self.assertEqual(group.activity_label, 'Flying')

    def test_editor_rejects_duplicates_bad_uploads_and_taken_recordings(self):
        first = self.recording()
        form = self.form(self.group_data([first.pk, first.pk]))
        self.assertFalse(form.is_valid())
        self.assertIn('only once', str(form.legs.non_form_errors()))
        self.assertEqual(Route.objects.count(), 1)
        taken = self.recording(parent=self.group())
        form = self.form(self.group_data([taken.pk]))
        self.assertFalse(form.is_valid())
        data = self.group_data(
            [None],
            **{
                'legs-0-route': '',
                'legs-0-name': 'Broken',
                'legs-0-activity_type': 'flying',
            },
        )
        form = self.form(
            data, files={'legs-0-file': SimpleUploadedFile('bad.gpx', b'not gpx')}
        )
        self.assertFalse(form.is_valid())
        self.assertIn('file', form.legs.errors[0])

    def test_stale_editor_cannot_move_a_leg_from_another_group(self):
        first = self.recording()
        form = self.form(self.group_data([first.pk]))
        self.assertTrue(form.is_valid(), form.errors)
        other = self.group()
        first.parent_route = other
        first.save()
        with self.assertRaises(ValidationError):
            form.save()
        self.assertEqual(Route.objects.filter(kind='group').count(), 1)
        first.refresh_from_db()
        self.assertEqual(first.parent_route_id, other.pk)

    def test_public_group_is_one_map_entry_with_mixed_mode_geometry(self):
        group = self.group(is_public=True)
        first = self.recording(parent=group)
        second = self.recording(mode='flying', parent=group, position=1)
        self.select(group)
        self.select(first, 1)
        self.page.save_revision().publish()
        response = self.client.get('/')
        manifest = response.context['map_routes']
        self.assertEqual(len(manifest), 1)
        self.assertEqual(manifest[0]['id'], group.pk)
        self.assertEqual(manifest[0]['leg_count'], 2)
        self.assertEqual(len(manifest[0]['stories']), 1)
        self.assertEqual(manifest[0]['activity_types'], ['cycling', 'flying'])
        payload = self.client.get(
            reverse('adventure-route-geojson', args=[group.pk])
        ).json()
        self.assertEqual(len(payload['features']), 2)
        self.assertEqual(
            [f['properties']['child_route_id'] for f in payload['features']],
            [first.pk, second.pk],
        )
        self.assertEqual(
            [f['properties']['activity_type'] for f in payload['features']],
            ['cycling', 'flying'],
        )
        self.assertTrue(
            all(len(f['geometry']['coordinates'][0]) == 3 for f in payload['features'])
        )
        overview = self.client.get(manifest[0]['url']).json()
        self.assertTrue(
            all(len(f['geometry']['coordinates'][0]) == 2 for f in overview['features'])
        )

    def test_overview_cache_revalidates_and_respects_visibility(self):
        caches['route_overviews'].clear()
        group = self.group(is_public=True)
        child = self.recording(parent=group)
        url = reverse('adventure-route-geojson', args=[group.pk]) + '?overview=1'

        call_command('warm_route_overviews', verbosity=0)
        self.client.force_login(self.admin)
        with patch(
            'django.db.models.fields.files.FieldFile.open',
            side_effect=AssertionError('cache miss'),
        ):
            first = self.client.get(url)
        self.assertEqual(first.status_code, 200)
        self.assertIn('must-revalidate', first['Cache-Control'])
        cached = self.client.get(url)
        self.assertEqual(cached.content, first.content)
        self.assertEqual(
            self.client.get(url, HTTP_IF_NONE_MATCH=first['ETag']).status_code,
            304,
        )

        child.activity_type = 'flying'
        child.save()
        changed = self.client.get(url, HTTP_IF_NONE_MATCH=first['ETag'])
        self.assertEqual(changed.status_code, 200)
        self.assertNotEqual(changed['ETag'], first['ETag'])
        self.assertEqual(
            changed.json()['features'][0]['properties']['activity_type'], 'flying'
        )

        child.file = SimpleUploadedFile('replacement.gpx', GPX)
        child.save()
        replaced = self.client.get(url, HTTP_IF_NONE_MATCH=changed['ETag'])
        self.assertEqual(replaced.status_code, 200)
        self.assertNotEqual(replaced['ETag'], changed['ETag'])

        group.is_public = False
        group.save()
        preview = self.client.get(url, HTTP_IF_NONE_MATCH=replaced['ETag'])
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview['Cache-Control'], 'private, no-store')
        self.assertNotIn('ETag', preview)
        self.client.logout()
        self.assertEqual(
            self.client.get(url, HTTP_IF_NONE_MATCH=replaced['ETag']).status_code,
            404,
        )

    def test_wagtail_group_edit_warms_new_overview_before_next_visit(self):
        caches['route_overviews'].clear()
        group = self.group(is_public=True)
        first = self.recording(parent=group)
        second = self.recording(name='New leg')
        url = reverse('adventure-route-geojson', args=[group.pk]) + '?overview=1'
        old_etag = self.client.get(url)['ETag']

        form = self.form(
            self.group_data(
                [first.pk, second.pk],
                is_public='on',
                **{'legs-INITIAL_FORMS': '1'},
            ),
            instance=group,
        )
        self.assertTrue(form.is_valid(), form.errors)
        with self.captureOnCommitCallbacks(execute=True):
            form.save()
        self.assertEqual(
            list(Route.objects.filter(parent_route=group).values_list('pk', flat=True)),
            [first.pk, second.pk],
        )

        with patch(
            'django.db.models.fields.files.FieldFile.open',
            side_effect=AssertionError('overview was not warmed'),
        ):
            updated = self.client.get(url, HTTP_IF_NONE_MATCH=old_etag)
        self.assertEqual(updated.status_code, 200)
        self.assertNotEqual(updated['ETag'], old_etag)
        self.assertEqual(len(updated.json()['features']), 2)

    def test_wagtail_recording_edit_warms_new_overview_before_next_visit(self):
        caches['route_overviews'].clear()
        route = self.recording(is_public=True)
        url = reverse('adventure-route-geojson', args=[route.pk]) + '?overview=1'
        old_etag = self.client.get(url)['ETag']

        form = self.form(
            {
                'kind': 'recording',
                'name': route.name,
                'activity_type': 'flying',
                'is_public': 'on',
            },
            instance=route,
            files={'file': SimpleUploadedFile('replacement.gpx', GPX)},
        )
        self.assertTrue(form.is_valid(), form.errors)
        with self.captureOnCommitCallbacks(execute=True):
            form.save()

        with patch(
            'django.db.models.fields.files.FieldFile.open',
            side_effect=AssertionError('overview was not warmed'),
        ):
            updated = self.client.get(url, HTTP_IF_NONE_MATCH=old_etag)
        self.assertEqual(updated.status_code, 200)
        self.assertNotEqual(updated['ETag'], old_etag)
        self.assertEqual(
            updated.json()['features'][0]['properties']['activity_type'], 'flying'
        )

    def test_public_leg_does_not_publish_private_group_or_sibling(self):
        group = self.group()
        child = self.recording(parent=group, is_public=True)
        private = self.recording(parent=group, position=1)
        visible = set(public_routes().values_list('pk', flat=True))
        self.assertEqual(visible, {child.pk})
        self.assertEqual(
            self.client.get(
                reverse('adventure-route-geojson', args=[group.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse('adventure-route-geojson', args=[private.pk])
            ).status_code,
            404,
        )
        manifest = self.client.get('/').context['map_routes']
        self.assertEqual([r['id'] for r in manifest], [child.pk])
        self.assertNotContains(self.client.get('/'), group.name)

    def test_publishing_group_story_exposes_legs_and_unpublishing_hides_them(self):
        group = self.group()
        child = self.recording(parent=group)
        self.select(group)
        self.assertFalse(public_routes().exists())
        self.page.save_revision().publish()
        self.assertEqual(
            set(public_routes().values_list('pk', flat=True)), {group.pk, child.pk}
        )
        self.page.refresh_from_db()
        self.page.unpublish()
        self.assertFalse(public_routes().exists())

    def test_group_with_pending_leg_keeps_ready_geometry_visible(self):
        group = self.group(is_public=True)
        child = self.recording(parent=group)
        Route.objects.bulk_create(
            [Route(name='Pending', parent_route=group, file='draft.gpx', activity_type='flying')]
        )
        self.assertIn(group.pk, public_routes().values_list('pk', flat=True))
        response = self.client.get('/')
        self.assertEqual(
            [item['value'] for item in response.context['activity_filters']],
            ['cycling'],
        )
        payload = self.client.get(
            reverse('adventure-route-geojson', args=[group.pk])
        ).json()
        self.assertEqual(
            [f['properties']['child_route_id'] for f in payload['features']], [child.pk]
        )

    def test_wagtail_group_form_and_child_parent_details_render(self):
        self.client.force_login(self.admin)
        group = self.group()
        child = self.recording(parent=group)
        self.assertContains(
            self.client.get(f'/cms/snippets/adventures/route/edit/{group.pk}/'),
            'Add a leg',
        )
        self.assertContains(
            self.client.get(f'/cms/snippets/adventures/route/edit/{child.pk}/'),
            'Part of:',
        )
        response = self.client.post(
            '/cms/snippets/adventures/route/add/',
            self.group_data([self.recording(name='Available').pk]),
        )
        self.assertEqual(response.status_code, 302)
