from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from django.test import RequestFactory


def warm_route_overview(route_id):
    from adventures.views import route_geojson

    request = RequestFactory().get('/?overview=1')
    request.user = AnonymousUser()
    try:
        route_geojson(request, route_id)
    except Http404:
        return False
    return True
