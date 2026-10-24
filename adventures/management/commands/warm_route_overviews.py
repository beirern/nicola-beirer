from django.contrib.auth.models import AnonymousUser
from django.core.management.base import BaseCommand
from django.http import Http404
from django.test import RequestFactory

from adventures.views import displayed_routes, public_routes, route_geojson


class Command(BaseCommand):
    help = 'Build public map route overviews before serving requests.'

    def handle(self, *args, **options):
        request = RequestFactory().get('/?overview=1')
        request.user = AnonymousUser()
        warmed = 0
        for route in displayed_routes(public_routes()):
            try:
                route_geojson(request, route.pk)
            except (Http404, OSError, ValueError) as exc:
                self.stderr.write(f'Could not warm route {route.pk}: {exc}')
                continue
            warmed += 1
        self.stdout.write(f'Warmed {warmed} map route overviews.')
