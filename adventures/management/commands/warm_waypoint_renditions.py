from django.core.management.base import BaseCommand
from wagtail.images.models import Rendition

from adventures.models import WaypointPhoto


class Command(BaseCommand):
    help = 'Build waypoint photo renditions so visitors never wait on a resize.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--rebuild', action='store_true',
            help='Delete existing renditions of waypoint photos first, so they are '
                 'rebuilt with the current storage settings (e.g. Cache-Control).',
        )

    def handle(self, *args, **options):
        photos = WaypointPhoto.objects.select_related('image')
        if options['rebuild']:
            image_ids = {photo.image_id for photo in photos}
            deleted, _ = Rendition.objects.filter(image_id__in=image_ids).delete()
            self.stdout.write(f'Deleted {deleted} renditions.')
        for photo in photos:
            photo.warm_renditions()
        self.stdout.write(f'Warmed renditions for {photos.count()} waypoint photos.')
