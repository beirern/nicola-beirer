"""One-time backfill for average distance per active day."""

from django.core.management.base import BaseCommand
from django.db import transaction

from adventures.models import AdventurePage


def add_average(stats):
    """Return updated saved stats, or None when the day count is unavailable."""
    if not stats or not stats.get('active_days'):
        return None
    updated = dict(stats)
    updated['avg_distance_km_per_active_day'] = round(
        (stats.get('distance_km') or 0) / stats['active_days'], 1
    )
    return updated


class Command(BaseCommand):
    help = 'Backfill saved average distance per active day without reparsing activity files.'

    def handle(self, *args, **options):
        updated_count = 0
        missing_days = []

        for page in AdventurePage.objects.exclude(computed_stats__isnull=True).iterator():
            if 'avg_distance_km_per_active_day' in page.computed_stats:
                continue
            updated = add_average(page.computed_stats)
            if updated is None:
                missing_days.append(page.pk)
                continue

            with transaction.atomic():
                AdventurePage.objects.filter(pk=page.pk).update(computed_stats=updated)
                latest = page.get_latest_revision_as_object()
                revision_stats = latest.computed_stats
                if revision_stats and 'avg_distance_km_per_active_day' not in revision_stats:
                    updated_revision = add_average(revision_stats)
                    if updated_revision is not None:
                        latest.computed_stats = updated_revision
                        latest.save_revision(clean=False)
            updated_count += 1

        self.stdout.write(f'Updated {updated_count} adventure(s).')
        if missing_days:
            self.stdout.write(
                f'Skipped {len(missing_days)} adventure(s) without active days: '
                + ', '.join(map(str, missing_days))
            )
