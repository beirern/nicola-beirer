"""Keep old revision recordings out of the everyday route listing."""

from functools import cached_property

import django_filters
from django import forms
from django.db.models import Q
from wagtail.admin.filters import WagtailFilterSet
from wagtail.models import Revision

from adventures.models import AdventurePage, Route


class RouteFilterSet(WagtailFilterSet):
    usage = django_filters.ChoiceFilter(
        label='Route records',
        choices=[
            ('current', 'Current routes'),
            ('historical', 'Historical only'),
            ('all', 'All routes'),
        ],
        empty_label=None,
        widget=forms.RadioSelect,
        method='filter_usage',
    )

    class Meta:
        model = Route
        fields = ['usage', 'kind', 'activity_type', 'is_public']

    def __init__(self, data=None, *args, **kwargs):
        data = data.copy() if data is not None else {}
        if not data.get('usage'):
            data['usage'] = 'current'
        super().__init__(data, *args, **kwargs)

    @cached_property
    def historical_ids(self):
        # A newly uploaded standalone route is current even before it is used.
        # Only hide routes known to be used exclusively by older revisions.
        latest = set(AdventurePage.objects.values_list('latest_revision_id', flat=True))
        referenced, current_drafts = set(), set()
        revisions = Revision.objects.filter(
            content_type__app_label='adventures', content_type__model='adventurepage'
        ).values_list('pk', 'content', 'approved_go_live_at')
        for pk, content, scheduled in revisions.iterator():
            ids = {
                int(link['route'])
                for link in content.get('adventure_routes', [])
                if link.get('route') is not None
            }
            referenced.update(ids)
            if pk in latest or scheduled:
                current_drafts.update(ids)
        in_use = Route.objects.filter(
            Q(adventure_links__isnull=False)
            | Q(is_public=True)
            | Q(parent_route__isnull=False)
            | Q(children__isnull=False)
        ).values_list('pk', flat=True)
        return referenced - current_drafts - set(in_use)

    def filter_usage(self, queryset, name, value):
        if value == 'all':
            return queryset
        if value == 'historical':
            return queryset.filter(pk__in=self.historical_ids)
        return queryset.exclude(pk__in=self.historical_ids)
