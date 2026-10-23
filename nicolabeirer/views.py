from django.conf import settings
from django.shortcuts import render
from adventures.views import route_manifest

from adventures.models import Route
from blog.models import BlogPage
from projects.models import ResumeProject


ROUTE_ACTIVITY_COLORS = {
    'hiking': '#57683f',
    'cycling': '#a8532e',
    'running': '#9b3f70',
    'skiing': '#366b9a',
    'climbing': '#8b5e34',
    'mountaineering': '#62558f',
    'kayaking': '#167f86',
    'sailing': '#285a91',
    'other': '#5f6670',
}


def home(request):
    map_routes = route_manifest(request)
    visible_activities = {
        activity for route in map_routes for activity in route['activity_types']
    }
    context = {
        'map_routes': map_routes,
        'activity_filters': [
            {
                'value': value,
                'label': label,
                'color': ROUTE_ACTIVITY_COLORS[value],
            }
            for value, label in Route.ActivityType.choices
            if value in visible_activities
        ],
        'carto_api_key': settings.CARTO_API_KEY,
        'recent_posts': BlogPage.objects.live().order_by('-date')[:3],
        'recent_projects': ResumeProject.objects.all()[:3],
    }
    return render(request, 'home.html', context)
