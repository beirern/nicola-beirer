"""Move existing adventure tracks into standalone Route files.

Run this only during the coordinated route cutover, after the schema migration.
"""

from django.core.management.base import BaseCommand
from adventures.models import AdventurePage
from adventures.services import process_adventure_files


class Command(BaseCommand):
    help = 'Reparse existing adventure files into standalone Route objects.'

    def handle(self, *args, **options):
        pages = AdventurePage.objects.filter(
            activity_files__pk__isnull=False,
            activity_files__route__isnull=True,
        ).distinct().order_by('pk')
        for page in pages.iterator():
            process_adventure_files(page)
            self.stdout.write(f'Reprocessed adventure {page.pk}: {page.title}')
