from django.shortcuts import render
from adventures.views import route_manifest, waypoint_manifest

from adventures.models import Route
from blog.models import BlogPage
from projects.models import ResumeProject


ROUTE_ACTIVITY_COLORS = {
    'cycling': '#a8532e',
    'hiking': '#75822f',
    'mountaineering': '#62558f',
    'flying': '#285a91',
    'train': '#397563',
    'commercial_flight': '#538baf',
}


def home(request):
    map_routes = route_manifest(request)
    visible_activities = {
        activity for route in map_routes for activity in route['activity_types']
    }
    context = {
        'map_routes': map_routes,
        'map_waypoints': waypoint_manifest(),
        'activity_filters': [
            {
                'value': value,
                'label': label,
                'color': ROUTE_ACTIVITY_COLORS[value],
            }
            for value, label in Route.ActivityType.choices
            if value in visible_activities
        ],
        'recent_posts': BlogPage.objects.live().order_by('-date')[:3],
        'recent_projects': ResumeProject.objects.all()[:3],
    }
    return render(request, 'home.html', context)
