from django.core.management.base import BaseCommand
from wagtail.images.models import Rendition

from nicolabeirer.renditions import all_images, warm


class Command(BaseCommand):
    help = 'Build the renditions the public pages show so visitors never wait on a resize.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--rebuild', action='store_true',
            help='Delete the renditions this command builds first, so they are '
                 'rebuilt with the current storage settings (e.g. Cache-Control).',
        )

    def handle(self, *args, **options):
        wanted = {}
        for image, specs in all_images():
            if image is not None:
                wanted.setdefault(image.pk, (image, set()))[1].update(specs)

        if options['rebuild']:
            deleted = 0
            for image, specs in wanted.values():
                count, _ = Rendition.objects.filter(image=image, filter_spec__in=specs).delete()
                deleted += count
            self.stdout.write(f'Deleted {deleted} renditions.')

        for image, specs in wanted.values():
            warm(image, sorted(specs))
        self.stdout.write(f'Warmed renditions for {len(wanted)} images.')
