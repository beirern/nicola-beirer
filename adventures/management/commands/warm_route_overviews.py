from django.core.management.base import BaseCommand

from adventures.map_cache import warm_route_overview
from adventures.views import displayed_routes, public_routes


class Command(BaseCommand):
    help = 'Build public map route overviews before serving requests.'

    def handle(self, *args, **options):
        warmed = 0
        for route in displayed_routes(public_routes()):
            try:
                ready = warm_route_overview(route.pk)
            except (OSError, ValueError) as exc:
                self.stderr.write(f'Could not warm route {route.pk}: {exc}')
                continue
            warmed += ready
        self.stdout.write(f'Warmed {warmed} map route overviews.')
