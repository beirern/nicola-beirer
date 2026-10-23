from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from wagtail.models import Page

from adventures.models import AdventureIndexPage, AdventurePage, AdventureRoute, Route
from adventures.tests import GPX


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'
        },
    }
)
class RouteListingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(
            'routefilter', 'admin@example.com', 'password'
        )
        index = Page.objects.get(depth=1).add_child(
            instance=AdventureIndexPage(title='Adventures', slug='adventures')
        )
        cls.page = index.add_child(
            instance=AdventurePage(title='Trip', slug='trip', live=False)
        )
        cls.old = Route.objects.create(
            name='Old recording', file=SimpleUploadedFile('old.gpx', GPX)
        )
        cls.current = Route.objects.create(
            name='Current recording', file=SimpleUploadedFile('current.gpx', GPX)
        )
        AdventureRoute.objects.create(page=cls.page, route=cls.old, sort_order=0)
        cls.page.save_revision().publish()
        cls.page.adventure_routes.all().delete()
        AdventureRoute.objects.create(page=cls.page, route=cls.current, sort_order=0)
        cls.page.save_revision().publish()

    def listing_ids(self, params=None):
        self.client.force_login(self.admin)
        response = self.client.get('/cms/snippets/adventures/route/', params or {})
        self.assertEqual(response.status_code, 200)
        return set(
            response.context['object_list'].values_list('pk', flat=True)
        ), response

    def test_default_hides_history_but_keeps_new_standalone_routes(self):
        standalone = Route.objects.create(
            name='New unused route', file=SimpleUploadedFile('new.gpx', GPX)
        )
        ids, response = self.listing_ids()
        self.assertEqual(ids, {self.current.pk, standalone.pk})
        self.assertContains(response, 'Current routes')
        self.assertContains(response, 'All routes')
        self.assertContains(response, 'Historical only')
        self.assertTrue(Route.objects.filter(pk=self.old.pk).exists())

    def test_history_filters_and_direct_edit_keep_old_recordings_accessible(self):
        ids, _ = self.listing_ids({'usage': 'all'})
        self.assertEqual(ids, {self.old.pk, self.current.pk})
        ids, _ = self.listing_ids({'usage': 'historical'})
        self.assertEqual(ids, {self.old.pk})
        self.assertEqual(
            self.client.get(
                f'/cms/snippets/adventures/route/edit/{self.old.pk}/'
            ).status_code,
            200,
        )
        ids, _ = self.listing_ids({'q': 'Old recording'})
        self.assertEqual(ids, set())
        ids, _ = self.listing_ids({'q': 'Old recording', 'usage': 'all'})
        self.assertEqual(ids, {self.old.pk})

    def test_latest_draft_and_group_members_are_current(self):
        draft = self.page.get_latest_revision_as_object()
        draft.adventure_routes.set([AdventureRoute(route=self.old, sort_order=0)])
        draft.save_revision()
        ids, _ = self.listing_ids()
        self.assertEqual(ids, {self.old.pk, self.current.pk})
        self.page.save_revision()
        group = Route.objects.create(name='Group', kind='group')
        self.old.parent_route = group
        self.old.save()
        ids, _ = self.listing_ids()
        self.assertEqual(ids, {self.old.pk, self.current.pk, group.pk})
