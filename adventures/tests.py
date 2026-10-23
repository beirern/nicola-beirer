import io
import json
from datetime import datetime, timezone
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from wagtail.models import Page

from adventures.models import AdventureRoute, AdventureIndexPage, AdventurePage, Route
from adventures.services import _fit_activity_dates, aggregate_stats, parse_gpx_file


class ActiveDayStatsTests(SimpleTestCase):
    def test_gpx_skips_rest_day_and_counts_both_moving_days(self):
        gpx = b"""<?xml version="1.0"?>
        <gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="40.000" lon="-73.000"><time>2026-10-01T10:00:00Z</time></trkpt>
            <trkpt lat="40.010" lon="-73.000"><time>2026-10-01T11:00:00Z</time></trkpt>
            <trkpt lat="40.010" lon="-73.000"><time>2026-10-02T10:00:00Z</time></trkpt>
            <trkpt lat="40.010" lon="-73.000"><time>2026-10-02T11:00:00Z</time></trkpt>
            <trkpt lat="40.020" lon="-73.000"><time>2026-10-03T10:00:00Z</time></trkpt>
            <trkpt lat="40.030" lon="-73.000"><time>2026-10-03T11:00:00Z</time></trkpt>
          </trkseg></trk>
        </gpx>"""
        stats = parse_gpx_file(io.BytesIO(gpx))['stats']

        self.assertEqual(stats['activity_dates'], ['2026-10-01', '2026-10-03'])
        self.assertEqual(aggregate_stats([stats])['active_days'], 2)
        self.assertEqual(aggregate_stats([stats])['avg_hours_per_active_day'], 1.0)

    def test_aggregate_deduplicates_dates_across_files(self):
        stats = aggregate_stats(
            [
                {
                    'moving_time_s': 7200,
                    'distance_km': 30,
                    'activity_dates': ['2026-10-01'],
                },
                {
                    'moving_time_s': 3600,
                    'distance_km': 10,
                    'activity_dates': ['2026-10-01', '2026-10-03'],
                },
            ]
        )

        self.assertEqual(stats['active_days'], 2)
        self.assertEqual(stats['avg_hours_per_active_day'], 1.5)
        self.assertEqual(stats['avg_distance_km_per_active_day'], 20.0)

    def test_aggregate_hides_average_when_existing_file_has_no_dates(self):
        stats = aggregate_stats(
            [
                {'moving_time_s': 3600},
                {'moving_time_s': 3600, 'activity_dates': ['2026-10-03']},
            ]
        )

        self.assertIsNone(stats['active_days'])
        self.assertIsNone(stats['avg_hours_per_active_day'])
        self.assertIsNone(stats['avg_distance_km_per_active_day'])

    def test_aggregate_hides_distance_average_when_distance_has_no_dates(self):
        stats = aggregate_stats(
            [
                {'distance_km': 10},
                {'distance_km': 10, 'activity_dates': ['2026-10-03']},
            ]
        )

        self.assertIsNone(stats['active_days'])
        self.assertIsNone(stats['avg_distance_km_per_active_day'])

    def test_fit_dates_require_movement(self):
        def sample(day, hour, speed):
            return (datetime(2026, 10, day, hour, tzinfo=timezone.utc), speed, None)

        records = [
            sample(1, 10, 2),
            sample(1, 11, 2),
            sample(2, 10, 0),
            sample(2, 11, 0),
        ]

        self.assertEqual(_fit_activity_dates(records), ['2026-10-01'])


GPX = b"""<?xml version="1.0"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
<trk><trkseg>
<trkpt lat="40.000" lon="-73.000"><ele>10</ele><time>2026-10-01T10:00:00Z</time></trkpt>
<trkpt lat="40.010" lon="-73.000"><ele>20</ele><time>2026-10-01T10:10:00Z</time></trkpt>
</trkseg></trk></gpx>"""


@override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'
        },
    }
)
class RouteLibraryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        root = Page.objects.get(depth=1)
        from wagtail.models import Site

        Site.objects.update(root_page=root)
        cls.index = root.add_child(
            instance=AdventureIndexPage(title='Adventures', slug='adventures')
        )
        cls.page = cls.index.add_child(
            instance=AdventurePage(title='Test trip', slug='test-trip', live=False)
        )

    def route(self, **kwargs):
        return Route.objects.create(
            name='A ride',
            activity_type='cycling',
            file=SimpleUploadedFile('ride.gpx', GPX),
            **kwargs,
        )

    def link(self, route):
        return AdventureRoute.objects.create(page=self.page, route=route, sort_order=0)

    def test_upload_and_metadata_edits_do_not_reparse(self):
        route = self.route()
        self.assertGreater(route.distance_km, 0)
        self.assertEqual(route.date_start.isoformat(), '2026-10-01')
        old_geometry = route.geojson_file.name
        with patch('adventures.services.parse_route_file') as parser:
            route.description = 'Along the coast'
            route.full_clean()
            route.save()
            parser.assert_not_called()
        self.assertEqual(route.geojson_file.name, old_geometry)

    def test_replacing_recording_recomputes_route_and_linked_stats(self):
        route = self.route()
        self.link(route)
        original = route.distance_km
        route.file = SimpleUploadedFile(
            'replacement.gpx', GPX.replace(b'40.010', b'40.030')
        )
        route.full_clean()
        route.save()
        self.assertGreater(route.distance_km, original)
        page = AdventurePage.objects.get(pk=self.page.pk)
        self.assertEqual(page.effective_distance_km, route.distance_km)

    def test_admin_form_reports_invalid_upload_without_saving(self):
        from wagtail.admin.panels import get_edit_handler

        form_class = get_edit_handler(Route).get_form_class()
        form = form_class(
            data={'name': 'Broken', 'activity_type': 'hiking'},
            files={'file': SimpleUploadedFile('bad.gpx', b'not xml')},
        )
        self.assertFalse(form.is_valid())
        self.assertIn('file', form.errors)
        self.assertEqual(Route.objects.count(), 0)

    def test_drafts_are_private_and_standalone_routes_can_be_public(self):
        route = self.route()
        self.link(route)
        url = reverse('adventure-route-geojson', args=[route.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        route.is_public = True
        route.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b''.join(response.streaming_content))
        home = self.client.get('/')
        self.assertContains(home, 'A ride')
        self.assertNotContains(home, 'Test trip')

    def test_published_story_supplies_map_links_but_restricted_story_does_not(self):
        from wagtail.models import PageViewRestriction

        route = self.route()
        self.link(route)
        self.page.save_revision().publish()
        home = self.client.get('/')
        self.assertContains(home, 'Read the story: Test trip')
        PageViewRestriction.objects.create(page=self.index, restriction_type='login')
        self.assertNotContains(self.client.get('/'), 'A ride')
        route.is_public = True
        route.save()
        home = self.client.get('/')
        self.assertContains(home, 'A ride')
        self.assertNotContains(home, 'Test trip')

    def test_multiple_routes_do_not_duplicate_story_links(self):
        first, second = self.route(), self.route()
        self.link(first)
        AdventureRoute.objects.create(page=self.page, route=second, sort_order=1)
        self.page.save_revision().publish()
        response = self.client.get('/')
        routes = response.context['map_routes']
        self.assertEqual(len(routes), 2)
        self.assertTrue(all(len(route['stories']) == 1 for route in routes))

    def test_home_routes_use_activity_recency_and_adventure_intro(self):
        linked = self.route(description='Recording notes')
        newest = self.route(is_public=True)
        undated = self.route(is_public=True)
        newest.parsed_stats = {
            **newest.parsed_stats,
            'date_start': '2026-09-01',
            'date_end': '2026-10-05',
        }
        newest.save(update_fields=['parsed_stats'])
        undated.parsed_stats = {
            key: value for key, value in undated.parsed_stats.items()
            if key not in ('date_start', 'date_end', 'activity_dates')
        }
        undated.save(update_fields=['parsed_stats'])
        self.link(linked)
        self.page.intro = 'The adventure summary'
        self.page.save_revision().publish()

        response = self.client.get('/')
        routes = response.context['map_routes']
        self.assertEqual([route['id'] for route in routes], [newest.pk, linked.pk, undated.pk])
        self.assertEqual(routes[1]['description'], 'The adventure summary')
        self.assertNotContains(response, 'Recording notes')
        self.assertContains(response, 'The adventure summary')
        self.assertContains(response, 'data-unit-toggle')
        self.assertNotContains(response, 'Latest from Adventures')

        self.page.intro = ''
        self.page.save_revision().publish()
        fallback = self.client.get('/').context['map_routes']
        self.assertEqual(fallback[1]['description'], 'Recording notes')

    def test_home_filters_include_only_visible_activity_types(self):
        self.route(is_public=True)
        running = self.route(is_public=True)
        running.activity_type = 'running'
        running.save(update_fields=['activity_type'])

        response = self.client.get('/')
        self.assertEqual(
            [item['value'] for item in response.context['activity_filters']],
            ['cycling', 'running'],
        )
        self.assertContains(response, 'data-route-filter="running"')
        self.assertNotContains(response, 'data-route-filter="hiking"')
        self.assertEqual(
            response.context['activity_filters'][1]['color'], '#9b3f70'
        )

    def test_overrides_do_not_change_daily_averages(self):
        route = self.route()
        self.link(route)
        page = AdventurePage.objects.get(pk=self.page.pk)
        stats = page.computed_stats
        self.assertEqual(page.effective_date_start, route.date_start)
        self.assertEqual(page.activity_type, 'Cycling')
        page.date_start = datetime(2026, 9, 1).date()
        page.date_end = datetime(2026, 11, 1).date()
        page.distance_km = 500
        page.elevation_gain_m = 999
        page.save()
        self.assertEqual(page.computed_stats, stats)
        self.assertEqual(page.effective_distance_km, 500)
        self.assertEqual(page.effective_elevation_gain_m, 999)
        self.assertEqual(page.computed_stats['active_days'], 1)

    def test_revision_restore_preserves_small_ordered_links(self):
        first = self.route()
        second = self.route()
        self.link(first)
        AdventureRoute.objects.create(page=self.page, route=second, sort_order=1)
        page = AdventurePage.objects.get(pk=self.page.pk)
        page.intro = 'A draft story'
        revision = page.save_revision()
        self.assertNotIn('40.010', json.dumps(revision.content))
        self.assertNotIn('activity_files', revision.content)
        self.assertNotIn('computed_stats', revision.content)
        restored = revision.as_object()
        self.assertEqual(
            [link.route_id for link in restored.adventure_routes.all()],
            [first.pk, second.pk],
        )
        self.assertEqual(restored.intro, 'A draft story')
        self.assertGreater(restored.effective_distance_km, 0)

    def test_publishing_and_renaming_adventure_updates_search_index(self):
        from wagtail.search.backends import get_search_backend

        backend = get_search_backend()
        with self.captureOnCommitCallbacks(execute=True):
            self.page.title = 'Ridgeway expedition'
            self.page.save_revision().publish()
        queryset = AdventurePage.objects.filter(pk=self.page.pk)
        self.assertEqual(
            [page.pk for page in backend.search('Ridgeway', queryset)],
            [self.page.pk],
        )

        with self.captureOnCommitCallbacks(execute=True):
            page = queryset.get()
            page.title = 'Coastway expedition'
            page.save_revision().publish()
        self.assertEqual(
            [page.pk for page in backend.search('Coastway', queryset)],
            [self.page.pk],
        )
        self.assertEqual(list(backend.search('Ridgeway', queryset)), [])

    def test_linked_route_deletion_is_protected(self):
        from django.db.models.deletion import ProtectedError

        route = self.route()
        self.link(route)
        with self.assertRaises(ProtectedError):
            route.delete()

    def test_full_geometry_and_simplified_geometry_endpoints(self):
        route = self.route(is_public=True)
        url = reverse('adventure-route-geojson', args=[route.pk])
        full = self.client.get(url)
        payload = json.loads(b''.join(full.streaming_content))
        self.assertEqual(len(payload['features'][0]['geometry']['coordinates'][0]), 3)
        overview = self.client.get(url + '?overview=1').json()
        self.assertEqual(len(overview['features'][0]['geometry']['coordinates'][0]), 2)

    def test_wagtail_admin_requires_login_and_exposes_route_library(self):
        from django.contrib.auth import get_user_model

        self.assertEqual(
            self.client.get('/cms/snippets/adventures/route/').status_code, 302
        )
        user = get_user_model().objects.create_superuser(
            'routeadmin', 'admin@example.com', 'password'
        )
        self.client.force_login(user)
        self.assertEqual(
            self.client.get('/cms/snippets/adventures/route/').status_code, 200
        )
        self.assertEqual(
            self.client.get('/cms/snippets/adventures/route/add/').status_code, 200
        )
        response = self.client.post(
            '/cms/snippets/adventures/route/add/',
            {
                'name': 'From admin',
                'activity_type': 'hiking',
                'file': SimpleUploadedFile('hike.gpx', GPX),
            },
        )
        self.assertEqual(response.status_code, 302)
        route = Route.objects.get(name='From admin')
        self.assertContains(
            self.client.get(f'/cms/snippets/adventures/route/edit/{route.pk}/'),
            'Recording details',
        )
        self.assertTrue(route.geojson_file)
        self.assertFalse(route.is_public)
        preview = self.client.get(reverse('adventure-route-geojson', args=[route.pk]))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview['Cache-Control'], 'private, no-store')
        self.assertTrue(b''.join(preview.streaming_content))
        self.link(route)
        deletion = self.client.get(f'/cms/snippets/adventures/route/delete/{route.pk}/')
        self.assertEqual(deletion.status_code, 200)
        self.assertTrue(deletion.context['is_protected'])
        self.assertEqual(
            self.client.post(
                f'/cms/snippets/adventures/route/delete/{route.pk}/',
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            ).status_code,
            403,
        )
        response = self.client.get(f'/cms/pages/{self.page.pk}/edit/')
        self.assertContains(response, 'adventure_routes')
        self.assertNotContains(response, 'activity_files')
