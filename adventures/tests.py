import io
from datetime import datetime, timezone
from unittest.mock import patch

from django.test import SimpleTestCase
from wagtail.models import Orderable

from adventures.models import ActivityFile
from adventures.services import _fit_activity_dates, aggregate_stats, parse_gpx_file


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
            parsed_stats={'moving_time_s': 3600},
            route_geojson={'type': 'Feature'},
            processed_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        with (patch.object(ActivityFile.objects, 'filter') as filtered,
              patch.object(Orderable, 'save')):
            filtered.return_value.values_list.return_value.first.return_value = 'activity_files/old.gpx'
            activity_file.save()

        self.assertEqual(activity_file.file_type, 'fit')
        self.assertIsNone(activity_file.parsed_stats)
        self.assertIsNone(activity_file.route_geojson)
        self.assertIsNone(activity_file.processed_at)
