from datetime import date
from hashlib import sha256
import json
import math

from django.core.cache import caches
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.cache import get_conditional_response

from adventures.models import AdventurePage, Route


def public_routes():
    """Groups publish their legs; public legs never publish a private parent."""
    stories = AdventurePage.objects.live().public()
    explicit = Route.objects.filter(
        Q(is_public=True) | Q(adventure_links__page__in=stories)
    )
    ready_recordings = Route.objects.filter(kind=Route.Kind.RECORDING).exclude(
        geojson_file=''
    )
    groups = explicit.filter(
        kind=Route.Kind.GROUP, pk__in=ready_recordings.values('parent_route_id')
    ).values('pk')
    recordings = (
        Route.objects.filter(kind=Route.Kind.RECORDING)
        .exclude(geojson_file='')
        .filter(Q(pk__in=explicit.values('pk')) | Q(parent_route_id__in=groups))
    )
    return Route.objects.filter(
        Q(pk__in=groups) | Q(pk__in=recordings.values('pk'))
    ).distinct()


def displayed_routes(visible):
    visible_groups = visible.filter(kind=Route.Kind.GROUP).values('pk')
    return visible.exclude(
        kind=Route.Kind.RECORDING, parent_route_id__in=visible_groups
    ).prefetch_related('children')


def route_manifest(request):
    """List a visible group once, with links from its own and its legs' stories."""
    visible = public_routes()
    display = displayed_routes(visible)
    stories = (
        AdventurePage.objects.live()
        .public()
        .filter(adventure_routes__route__in=visible)
        .distinct()
        .prefetch_related('adventure_routes__route__children')
    )
    story_links = {}
    for story in sorted(
        stories,
        key=lambda page: page.effective_date_end or page.effective_date_start or date.min,
        reverse=True,
    ):
        url = story.get_url(request)
        if url:
            for link in story.adventure_routes.all():
                story_links.setdefault(link.route_id, []).append(
                    {'title': story.title, 'url': url, 'description': story.intro}
                )
    result = []
    for route in display:
        activity_types = list(
            dict.fromkeys(
                recording.activity_type
                for recording in route.recordings
                if recording.geojson_file and recording.activity_type
            )
        )
        related_ids = list(
            dict.fromkeys([route.pk] + [leg.pk for leg in route.recordings])
        )
        linked = {}
        for pk in related_ids:
            for story in story_links.get(pk, []):
                linked.setdefault(story['url'], story)
        linked_stories = list(linked.values())
        result.append(
            {
                'id': route.pk,
                'name': route.name,
                'description': next(
                    (story['description'] for story in linked_stories if story['description']),
                    route.description,
                ),
                'activity_type': route.activity_type,
                'activity_types': activity_types,
                'activity_label': ' / '.join(
                    dict(Route.ActivityType.choices).get(mode, mode)
                    for mode in activity_types
                ),
                'leg_count': route.leg_count,
                'is_group': route.kind == Route.Kind.GROUP,
                'date_start': route.date_start,
                'date_end': route.date_end,
                'distance_km': route.distance_km,
                'url': reverse('adventure-route-geojson', args=[route.pk])
                + '?overview=1',
                'stories': [
                    {'title': story['title'], 'url': story['url']}
                    for story in linked_stories
                ],
            }
        )
    return sorted(
        result,
        key=lambda item: (
            item['date_end'] or item['date_start'] or date.min,
            item['date_start'] or date.min,
        ),
        reverse=True,
    )


def route_geojson(request, route_id):
    route = public_routes().filter(pk=route_id).first()
    is_preview = route is None
    if is_preview:
        if not request.user.is_authenticated or not (
            request.user.has_perm('adventures.view_route')
            or request.user.has_perm('adventures.change_route')
        ):
            raise Http404
        route = get_object_or_404(Route, pk=route_id)
    overview = request.GET.get('overview') == '1'
    recordings = route.recordings
    etag = None
    cache_key = None
    if overview and not is_preview:
        fingerprint = json.dumps(
            [
                (leg.pk, leg.position, leg.geojson_file.name, leg.activity_type)
                for leg in recordings
            ],
            separators=(',', ':'),
        )
        version = sha256(f'overview-v1:{route.pk}:{fingerprint}'.encode()).hexdigest()
        etag = f'"{version}"'
        cache_key = f'route-overview:v1:{version}'
        conditional = get_conditional_response(request, etag=etag)
        if conditional is not None:
            conditional['ETag'] = etag
            conditional['Cache-Control'] = 'public, max-age=0, must-revalidate'
            return conditional
    if route.kind == Route.Kind.RECORDING and not overview:
        if not route.geojson_file:
            raise Http404
        try:
            response = FileResponse(
                route.geojson_file.open('rb'), content_type='application/geo+json'
            )
        except FileNotFoundError as exc:
            raise Http404 from exc
    else:
        cached_body = caches['route_overviews'].get(cache_key) if cache_key else None
        if cached_body is not None:
            response = HttpResponse(cached_body, content_type='application/geo+json')
        else:
            features = []
            for recording in recordings:
                if not recording.geojson_file:
                    continue
                try:
                    with recording.geojson_file.open('rb') as source:
                        payload = json.load(source)
                except FileNotFoundError as exc:
                    raise Http404 from exc
                for feature in payload['features']:
                    feature['properties'] = {
                        **feature.get('properties', {}),
                        'route_id': route.pk,
                        'child_route_id': recording.pk,
                        'activity_type': recording.activity_type,
                    }
                    if overview:
                        coords = feature['geometry']['coordinates']
                        stride = max(1, math.ceil(len(coords) / 1500))
                        simplified = [point[:2] for point in coords[::stride]]
                        if coords and simplified[-1] != coords[-1][:2]:
                            simplified.append(coords[-1][:2])
                        feature['geometry']['coordinates'] = simplified
                    features.append(feature)
            if not features:
                raise Http404
            response = JsonResponse(
                {'type': 'FeatureCollection', 'features': features},
                content_type='application/geo+json',
            )
            if cache_key:
                caches['route_overviews'].set(cache_key, response.content)
    if etag:
        response['ETag'] = etag
    response['Cache-Control'] = (
        'private, no-store' if is_preview else 'public, max-age=0, must-revalidate'
    )
    return response
