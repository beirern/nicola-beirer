from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from adventures.models import Route


def route_geojson(request, route_id):
    route = get_object_or_404(
        Route.objects.filter(activity_files__page__live=True).distinct(), pk=route_id
    )
    if not route.geojson_file:
        raise Http404
    response = FileResponse(route.geojson_file.open('rb'), content_type='application/geo+json')
    response['Cache-Control'] = 'public, max-age=3600'
    return response
