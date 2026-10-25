"""Exercise the ownership migration against an isolated, pre-change database."""

import os
import subprocess
import sys

from django.test import SimpleTestCase


class RouteOwnershipMigrationTests(SimpleTestCase):
    def test_current_pages_and_historical_drafts_keep_their_routes(self):
        script = r"""
import django
from django.conf import settings
settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from datetime import date
from django.utils import timezone
executor = MigrationExecutor(connection)
executor.migrate([('adventures', '0012_drop_legacy_route_columns')])
old = executor.loader.project_state([('adventures', '0012_drop_legacy_route_columns')]).apps
Adventure = old.get_model('adventures', 'AdventurePage')
Route = old.get_model('adventures', 'Route')
Upload = old.get_model('adventures', 'ActivityFile')
Revision = old.get_model('wagtailcore', 'Revision')
ContentType = old.get_model('contenttypes', 'ContentType')
ct, _ = ContentType.objects.get_or_create(app_label='adventures', model='adventurepage')
stats = {'distance_km': 30, 'elevation_gain_m': 200, 'moving_time_s': 7200, 'activity_dates': ['2026-10-01']}
page = Adventure.objects.create(path='00010002', depth=2, numchild=0, title='Legacy story', slug='legacy', locale_id=1, content_type_id=ct.pk, date_start=date(2026, 10, 1), date_end=date(2026, 10, 1), activity_type='cycling', computed_stats=stats, distance_km=30)
route = Route.objects.create(name='ride.fit', geojson_file='routes/existing.geojson', distance_km=30, elevation_gain_m=200)
upload = Upload.objects.create(page=page, route=route, file='activity_files/ride.fit', file_type='fit', parsed_stats=stats, sort_order=0)
other_stats = {'distance_km': 0, 'elevation_gain_m': 0, 'activity_dates': ['2026-10-01']}
other = Route.objects.create(name='pause.fit', geojson_file='routes/pause.geojson', distance_km=0, elevation_gain_m=0)
other_upload = Upload.objects.create(page=page, route=other, file='activity_files/pause.fit', file_type='fit', parsed_stats=other_stats, sort_order=1)
shared_page = Adventure.objects.create(path='00010003', depth=2, numchild=0, title='Shared story', slug='shared', locale_id=1, content_type_id=ct.pk, date_start=date(2026, 10, 1), activity_type='cycling')
Upload.objects.create(page=shared_page, route=route, file='activity_files/ride.fit', file_type='fit', parsed_stats=stats, sort_order=0)
content = {'pk': page.pk, 'page_ptr': page.pk, 'title': 'Draft title', 'intro': 'Unpublished words', 'path': page.path, 'depth': 2, 'slug': 'legacy', 'locale': 1, 'content_type': ct.pk, 'date_start': '2026-10-01', 'date_end': '2026-10-01', 'activity_type': 'cycling', 'computed_stats': stats, 'distance_km': '30.00', 'activity_files': [{'pk': upload.pk, 'page': page.pk, 'route': route.pk, 'file': upload.file.name, 'file_type': 'fit', 'parsed_stats': stats, 'sort_order': 0}, {'pk': other_upload.pk, 'page': page.pk, 'route': other.pk, 'file': other_upload.file.name, 'file_type': 'fit', 'parsed_stats': other_stats, 'sort_order': 1}]}
revision = Revision.objects.create(created_at=timezone.now(), content_type_id=ct.pk, base_content_type_id=ct.pk, object_id=str(page.pk), content=content)
# A revision from before processing must reuse the same file rather than create a duplicate route.
content['activity_files'][0]['route'] = None
Revision.objects.create(created_at=timezone.now(), content_type_id=ct.pk, base_content_type_id=ct.pk, object_id=str(page.pk), content=content)
# An unprocessed draft-only upload must survive as a private, editable route.
content['activity_files'][0] = {'pk': None, 'file': 'activity_files/draft.gpx', 'route': None, 'parsed_stats': None, 'sort_order': 0}
draft = Revision.objects.create(created_at=timezone.now(), content_type_id=ct.pk, base_content_type_id=ct.pk, object_id=str(page.pk), content=content)
executor = MigrationExecutor(connection)
executor.migrate(executor.loader.graph.leaf_nodes())
from adventures.models import AdventurePage, Route, AdventureRoute
from wagtail.models import Revision
page = AdventurePage.objects.get(pk=page.pk)
assert page.title == 'Legacy story'
assert page.date_start is None and page.date_end is None and page.distance_km is None
assert page.effective_date_start == date(2026, 10, 1)
assert page.computed_stats['active_days'] == 1
assert page.computed_stats['avg_distance_km_per_active_day'] == 30
assert page.activity_type == 'Cycling'
group = AdventureRoute.objects.get(page=page).route
assert group.kind == 'group' and group.name == page.title
assert list(group.children.order_by('position').values_list('pk', flat=True)) == [route.pk, other.pk]
assert page.effective_distance_km == 30
shared_group = AdventureRoute.objects.get(page_id=shared_page.pk).route
assert shared_group.kind == 'group' and shared_group.pk != group.pk
shared_leg = shared_group.children.get()
assert shared_leg.pk != route.pk and shared_leg.file.name == 'activity_files/ride.fit'
assert shared_leg.geojson_file.name == route.geojson_file.name
assert Route.objects.count() == 6
route = Route.objects.get(pk=route.pk)
assert route.kind == 'recording' and route.parent_route_id == group.pk
assert route.file.name == 'activity_files/ride.fit'
assert route.geojson_file.name == 'routes/existing.geojson'
assert route.distance_km == 30 and not route.is_public
revision = Revision.objects.get(pk=revision.pk)
assert 'activity_files' not in revision.content and 'computed_stats' not in revision.content
restored = revision.as_object()
assert restored.intro == 'Unpublished words'
assert [link.route_id for link in restored.adventure_routes.all()] == [group.pk]
restored.save_revision().publish()
assert AdventurePage.objects.get(pk=page.pk).intro == 'Unpublished words'
assert list(AdventurePage.objects.get(pk=page.pk).adventure_routes.values_list('route_id', flat=True)) == [group.pk]
draft = Revision.objects.get(pk=draft.pk).as_object()
draft_route = draft.adventure_routes.all()[0].route
assert draft_route.file.name == 'activity_files/draft.gpx'
assert not draft_route.is_public and not draft_route.geojson_file
assert draft.adventure_routes.all()[1].route_id == other.pk
"""
        result = subprocess.run(
            [sys.executable, '-c', script],
            env={**os.environ, 'MAPTILER_API_KEY': os.environ.get('MAPTILER_API_KEY', '')},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
