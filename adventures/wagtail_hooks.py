from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models.deletion import ProtectedError

from wagtail import hooks
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import (
    CreateView,
    EditView,
    DeleteView,
    SnippetViewSet,
)

from adventures.models import Route, Waypoint
from adventures.forms import RouteAdminForm, WaypointAdminForm
from adventures.filters import RouteFilterSet

Route.base_form_class = RouteAdminForm
Waypoint.base_form_class = WaypointAdminForm


class RouteDeleteView(DeleteView):
    """Protect links even before Wagtail's reference index has been rebuilt."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object.deletion_blocked:
            context['is_protected'] = True
            context['usage_count'] = (
                self.object.adventure_links.count()
                + self.object.children.count()
                + self.object.waypoints.count()
                + bool(self.object.parent_route_id)
            )
        return context

    def form_valid(self, form):
        if self.object.deletion_blocked:
            raise PermissionDenied(
                'Detach this route’s legs, waypoints, and adventure links before deleting it.'
            )
        try:
            return super().form_valid(form)
        except ProtectedError as exc:
            raise PermissionDenied('This route is still in use.') from exc


class RouteFormViewMixin:
    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)


class RouteCreateView(RouteFormViewMixin, CreateView):
    pass


class RouteEditView(RouteFormViewMixin, EditView):
    pass


class RouteViewSet(SnippetViewSet):
    model = Route
    delete_view_class = RouteDeleteView
    add_view_class = RouteCreateView
    edit_view_class = RouteEditView
    icon = 'site'
    menu_label = 'Routes'
    add_to_admin_menu = True
    list_display = [
        'name',
        'kind',
        'parent_route',
        'activity_label',
        'is_public',
        'processing_status',
    ]
    filterset_class = RouteFilterSet
    search_fields = ['name', 'description']
    chooser_per_page = 20

    def get_queryset(self, request):
        return Route.objects.select_related('parent_route').prefetch_related('children')


register_snippet(RouteViewSet)


class WaypointViewSet(SnippetViewSet):
    model = Waypoint
    icon = 'site'
    menu_label = 'Waypoints'
    add_to_admin_menu = True
    list_display = ['name', 'route', 'is_public']
    search_fields = ['name', 'description']


register_snippet(WaypointViewSet)


@hooks.register('before_delete_snippet')
def protect_grouped_routes(request, instances):
    # Bulk deletion uses a separate Wagtail view and bypasses model.delete().
    if request.method == 'POST' and any(
        isinstance(route, Route) and route.deletion_blocked for route in instances
    ):
        raise PermissionDenied(
            'Detach route legs, waypoints, and adventure links before deleting them.'
        )
