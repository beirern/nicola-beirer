import io
import json
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from wagtail.models import Orderable, Page

from adventures.models import ActivityFile, AdventureIndexPage, AdventurePage, Route
from adventures.services import _fit_activity_dates, aggregate_stats, parse_gpx_file, process_adventure_files


class ActiveDayStatsTests(SimpleTestCase):
    def test_gpx_skips_rest_day_and_counts_both_moving_days(self):
        gpx = b'''<?xml version="1.0"?>
        <gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="40.000" lon="-73.000"><time>2026-10-01T10:00:00Z</time></trkpt>
            <trkpt lat="40.010" lon="-73.000"><time>2026-10-01T11:00:00Z</time></trkpt>
            <trkpt lat="40.010" lon="-73.000"><time>2026-10-02T10:00:00Z</time></trkpt>
            <trkpt lat="40.010" lon="-73.000"><time>2026-10-02T11:00:00Z</time></trkpt>
            <trkpt lat="40.020" lon="-73.000"><time>2026-10-03T10:00:00Z</time></trkpt>
            <trkpt lat="40.030" lon="-73.000"><time>2026-10-03T11:00:00Z</time></trkpt>
          </trkseg></trk>
        </gpx>'''
        stats = parse_gpx_file(io.BytesIO(gpx))['stats']

        self.assertEqual(stats['activity_dates'], ['2026-10-01', '2026-10-03'])
        self.assertEqual(aggregate_stats([stats])['active_days'], 2)
        self.assertEqual(aggregate_stats([stats])['avg_hours_per_active_day'], 1.0)

    def test_aggregate_deduplicates_dates_across_files(self):
        stats = aggregate_stats([
            {'moving_time_s': 7200, 'activity_dates': ['2026-10-01']},
            {'moving_time_s': 3600, 'activity_dates': ['2026-10-01', '2026-10-03']},
        ])

        self.assertEqual(stats['active_days'], 2)
        self.assertEqual(stats['avg_hours_per_active_day'], 1.5)

    def test_aggregate_hides_average_when_existing_file_has_no_dates(self):
        stats = aggregate_stats([
            {'moving_time_s': 3600},
            {'moving_time_s': 3600, 'activity_dates': ['2026-10-03']},
        ])

        self.assertIsNone(stats['active_days'])
        self.assertIsNone(stats['avg_hours_per_active_day'])

    def test_fit_dates_require_movement(self):
        def sample(day, hour, speed):
            return (datetime(2026, 10, day, hour, tzinfo=timezone.utc), speed, None)

        records = [
            sample(1, 10, 2), sample(1, 11, 2),
            sample(2, 10, 0), sample(2, 11, 0),
        ]

        self.assertEqual(_fit_activity_dates(records), ['2026-10-01'])

    def test_replacing_file_marks_it_for_reprocessing(self):
        activity_file = ActivityFile(
            pk=1,
            file='activity_files/new.fit',
            file_type='gpx',
            route_id=5,
            parsed_stats={'moving_time_s': 3600},
            processed_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        with (patch.object(ActivityFile.objects, 'filter') as filtered,
              patch.object(Orderable, 'save')):
            filtered.return_value.values_list.return_value.first.return_value = 'activity_files/old.gpx'
            activity_file.save()

        self.assertEqual(activity_file.file_type, 'fit')
        self.assertIsNone(activity_file.parsed_stats)
        self.assertIsNone(activity_file.route)
        self.assertIsNone(activity_file.processed_at)


class RouteStorageTests(TestCase):
    def test_processing_keeps_geometry_out_of_page_revisions_and_serves_route(self):
        root = Page.objects.get(depth=1)
        index = root.add_child(instance=AdventureIndexPage(title='Adventures', slug='adventures'))
        page = index.add_child(instance=AdventurePage(title='Test trip', slug='test-trip'))
        gpx = b'''<?xml version="1.0"?>
        <gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="40.1234567" lon="-73.1234567"><ele>10</ele><time>2026-10-01T10:00:00Z</time></trkpt>
            <trkpt lat="40.2234567" lon="-73.2234567"><ele>20</ele><time>2026-10-01T11:00:00Z</time></trkpt>
          </trkseg></trk>
        </gpx>'''

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            activity_file = ActivityFile.objects.create(
                page=page,
                file=SimpleUploadedFile('trip.gpx', gpx, content_type='application/gpx+xml'),
            )
            process_adventure_files(page)

            activity_file.refresh_from_db()
            page.refresh_from_db()
            self.assertIsNotNone(activity_file.route_id)
            self.assertEqual(Route.objects.count(), 1)

            revision = page.get_latest_revision().content
            self.assertNotIn('40.1234567', json.dumps(revision))
            self.assertEqual(revision['activity_files'][0]['route'], activity_file.route_id)

            response = self.client.get(reverse('adventure-route-geojson', args=[activity_file.route_id]))
            self.assertEqual(response.status_code, 200)
            payload = json.loads(b''.join(response.streaming_content))
            self.assertEqual(payload['features'][0]['geometry']['coordinates'][0][:2], [-73.1234567, 40.1234567])

            draft = page.get_latest_revision_as_object()
            draft.intro = 'Unpublished writing'
            draft.save_revision(clean=False)
            process_adventure_files(page)
            self.assertEqual(Route.objects.count(), 1)
            page.refresh_from_db()
            self.assertEqual(page.get_latest_revision_as_object().intro, 'Unpublished writing')
