from datetime import date, datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator, MaxValueValidator
from django.db import models
from django.urls import reverse
from django.utils.functional import cached_property
from modelcluster.contrib.taggit import ClusterTaggableManager
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from taggit.models import TaggedItemBase
from wagtail.admin.panels import FieldPanel, HelpPanel, InlinePanel, MultiFieldPanel
from wagtail.fields import RichTextField, StreamField
from wagtail.models import Orderable, Page

from blog.models import standard_body_blocks
from nicolabeirer.renditions import WAYPOINT_PHOTO, warm


class AdventurePageTag(TaggedItemBase):
    content_object = ParentalKey(
        'adventures.AdventurePage',
        related_name='tagged_items',
        on_delete=models.CASCADE,
    )


class WaypointMapPanel(HelpPanel):
    class BoundPanel(HelpPanel.BoundPanel):
        def get_context_data(self, parent_context=None):
            context = super().get_context_data(parent_context)
            context['maptiler_api_key'] = settings.MAPTILER_API_KEY
            return context


class Waypoint(ClusterableModel):
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=500, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.DecimalField(max_digits=9, decimal_places=6, validators=[MinValueValidator(-180), MaxValueValidator(180)])
    route = models.ForeignKey('adventures.Route', null=True, blank=True, on_delete=models.PROTECT, related_name='waypoints')
    is_public = models.BooleanField(default=False, verbose_name='Show on public map')

    panels = [
        FieldPanel('route'),
        FieldPanel('name'),
        FieldPanel('description'),
        FieldPanel('latitude'),
        FieldPanel('longitude'),
        WaypointMapPanel(template='adventures/admin/waypoint_map.html'),
        InlinePanel('photos', label='Photos'),
        FieldPanel('is_public'),
    ]

    def clean(self):
        super().clean()
        errors = {}
        if self.route_id and self.route.kind == 'recording' and self.route.parent_route_id:
            errors['route'] = 'Choose the group for a grouped recording.'
        if self.is_public and not self.route_id:
            errors['route'] = 'Choose a route before showing this waypoint on the public map.'
        if self.latitude is not None and self.longitude is not None:
            duplicates = type(self).objects.filter(latitude=self.latitude, longitude=self.longitude)
            if self.pk:
                duplicates = duplicates.exclude(pk=self.pk)
            if duplicates.exists():
                errors['latitude'] = 'Another waypoint already uses these exact coordinates. Move this marker slightly.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.name


def photo_taken_on(image):
    """Read the capture date from an image's EXIF data, or None when it has none."""
    try:
        from PIL import Image as PILImage

        with image.file.open('rb') as file, PILImage.open(file) as picture:
            exif = picture.getexif()
            stamp = exif.get_ifd(0x8769).get(0x9003) or exif.get(0x0132)
        return datetime.strptime(str(stamp)[:10], '%Y:%m:%d').date()
    except Exception:
        return None


class WaypointPhoto(Orderable):
    waypoint = ParentalKey(Waypoint, related_name='photos', on_delete=models.CASCADE)
    image = models.ForeignKey('wagtailimages.Image', on_delete=models.PROTECT, related_name='+')
    caption = models.CharField(max_length=500, blank=True)
    taken_on = models.DateField(
        null=True, blank=True,
        help_text='Shown before the caption. Filled from the photo when it has a capture date.',
    )

    panels = [FieldPanel('image'), FieldPanel('caption'), FieldPanel('taken_on')]

    def save(self, *args, **kwargs):
        if self.taken_on is None and self.image_id:
            self.taken_on = photo_taken_on(self.image)
        super().save(*args, **kwargs)
        self.warm_renditions()

    def warm_renditions(self):
        """Resize now so visitors never wait on the first map load or photo open."""
        warm(self.image, WAYPOINT_PHOTO)


class AdventureWaypoint(Orderable):
    page = ParentalKey('adventures.AdventurePage', related_name='adventure_waypoints', on_delete=models.CASCADE)
    waypoint = models.ForeignKey(Waypoint, on_delete=models.PROTECT, related_name='adventure_links')

    panels = [FieldPanel('waypoint')]


class Route(models.Model):
    """A recording or ordered group; geometry and statistics stay outside page revisions."""

    class ActivityType(models.TextChoices):
        CYCLING = 'cycling', 'Cycling'
        HIKING = 'hiking', 'Hiking'
        MOUNTAINEERING = 'mountaineering', 'Mountaineering'
        FLYING = 'flying', 'Flying'
        TRAIN = 'train', 'Train'
        COMMERCIAL_FLIGHT = 'commercial_flight', 'Commercial flight'

    class Kind(models.TextChoices):
        RECORDING = 'recording', 'Recording'
        GROUP = 'group', 'Group'

    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.RECORDING)
    parent_route = models.ForeignKey(
        'self', null=True, blank=True, related_name='children', on_delete=models.PROTECT
    )
    position = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    activity_type = models.CharField(
        max_length=20,
        choices=ActivityType.choices,
        default=ActivityType.CYCLING,
        blank=True,
    )
    manual_date_start = models.DateField(
        'Start date', null=True, blank=True,
        help_text='Optional. Overrides the start date from the recording or group legs.',
    )
    manual_date_end = models.DateField(
        'End date', null=True, blank=True,
        help_text='Optional. Overrides the end date from the recording or group legs. For a single-day route, set both dates to the same day.',
    )
    file = models.FileField(
        upload_to='activity_files/',
        default='',
        blank=True,
        validators=[FileExtensionValidator(['gpx', 'fit'])],
    )
    is_public = models.BooleanField(
        default=False,
        help_text='Show this route on the homepage map, even without a story. A published adventure also makes its selected routes accessible.',
    )
    geojson_file = models.FileField(upload_to='routes/', blank=True, editable=False)
    parsed_stats = models.JSONField(default=dict, blank=True, editable=False)
    min_longitude = models.FloatField(null=True, blank=True, editable=False)
    min_latitude = models.FloatField(null=True, blank=True, editable=False)
    max_longitude = models.FloatField(null=True, blank=True, editable=False)
    max_latitude = models.FloatField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    panels = [
        FieldPanel('kind'),
        FieldPanel('name'),
        FieldPanel('description'),
        MultiFieldPanel(
            [FieldPanel('manual_date_start'), FieldPanel('manual_date_end')],
            heading='Dates',
        ),
        MultiFieldPanel(
            [FieldPanel('activity_type'), FieldPanel('file')],
            heading='Recording',
            classname='route-recording-fields',
        ),
        FieldPanel('is_public'),
        HelpPanel(template='adventures/admin/route_legs.html'),
        HelpPanel(
            template='adventures/admin/route_recording_details.html',
            heading='Recording details',
        ),
    ]

    class Meta:
        ordering = ['name', 'pk']

    def __str__(self):
        if self.kind == self.Kind.GROUP:
            return f'{self.name} (group)'
        if self.parent_route_id:
            return f'{self.name} — part of {self.parent_route.name}'
        return self.name

    @cached_property
    def recordings(self):
        if self.kind == self.Kind.RECORDING:
            return [self]
        return (
            sorted(self.children.all(), key=lambda route: (route.position, route.pk))
            if self.pk
            else []
        )

    @property
    def leg_count(self):
        return len(self.recordings)

    @property
    def activity_types(self):
        return list(
            dict.fromkeys(
                route.activity_type for route in self.recordings if route.activity_type
            )
        )

    @property
    def activity_label(self):
        labels = dict(self.ActivityType.choices)
        return ' / '.join(labels.get(mode, mode) for mode in self.activity_types)

    @property
    def stats(self):
        from adventures.services import aggregate_stats

        if self.kind == self.Kind.RECORDING:
            return self.parsed_stats or {}
        return (
            aggregate_stats([route.parsed_stats or {} for route in self.recordings])
            if self.recordings
            else {}
        )

    def validate_structure(self):
        errors = {}
        if self.parent_route_id:
            if self.parent_route_id == self.pk or self.kind == self.Kind.GROUP:
                errors['parent_route'] = (
                    'Groups cannot be nested or belong to themselves.'
                )
            elif self.parent_route.kind != self.Kind.GROUP:
                errors['parent_route'] = 'The parent must be a group route.'
        if self.kind == self.Kind.GROUP and self.file:
            errors['file'] = (
                'A group uses its legs’ recordings; it cannot have its own file.'
            )
        if self.kind == self.Kind.RECORDING and self.pk and self.children.exists():
            errors['kind'] = (
                'Detach all legs before changing this group to a recording.'
            )
        if errors:
            raise ValidationError(errors)

    @property
    def processing_status(self):
        if self.kind == self.Kind.GROUP:
            ready = sum(bool(route.geojson_file) for route in self.recordings)
            return f'{ready} of {self.leg_count} legs ready'
        return (
            'Ready'
            if self.geojson_file
            else 'Save this route to process its recording.'
        )

    @property
    def deletion_blocked(self):
        return (
            bool(self.parent_route_id)
            or self.children.exists()
            or self.adventure_links.exists()
            or self.waypoints.exists()
        )

    def delete(self, *args, **kwargs):
        from django.db.models.deletion import ProtectedError

        if self.deletion_blocked:
            raise ProtectedError(
                'Detach this route and its legs, waypoints, and adventure links before deleting it.',
                {self},
            )
        return super().delete(*args, **kwargs)

    @property
    def bounds(self):
        points = [
            (
                route.min_longitude,
                route.min_latitude,
                route.max_longitude,
                route.max_latitude,
            )
            for route in self.recordings
        ]
        points = [
            point for point in points if all(value is not None for value in point)
        ]
        return (
            (
                min(p[0] for p in points),
                min(p[1] for p in points),
                max(p[2] for p in points),
                max(p[3] for p in points),
            )
            if points
            else None
        )

    def _file_changed(self):
        old = (
            type(self).objects.filter(pk=self.pk).values_list('file', flat=True).first()
            if self.pk
            else None
        )
        return (
            not self.geojson_file or not self.file._committed or self.file.name != old
        )

    def clean(self):
        super().clean()
        self.validate_structure()
        if self.date_start and self.date_end and self.date_end < self.date_start:
            raise ValidationError('The end date must be on or after the start date.')
        if self.kind == self.Kind.RECORDING and not self.file and not self.geojson_file:
            raise ValidationError({'file': 'Upload a GPX or FIT recording.'})
        if self.file and self._file_changed():
            from adventures.services import parse_route_file

            try:
                self._parsed_result = parse_route_file(self.file)
            except Exception as exc:
                raise ValidationError(
                    {
                        'file': 'Could not read this recording. Upload a valid GPX or FIT file with at least two GPS points.'
                    }
                ) from exc

    def save(self, *args, **kwargs):
        self.validate_structure()
        if self.kind == self.Kind.GROUP:
            self.activity_type = ''
            self.parsed_stats = {}
            self.geojson_file = ''
            self.min_longitude = self.min_latitude = self.max_longitude = (
                self.max_latitude
            ) = None
        if self.file and self._file_changed():
            from adventures.services import parse_route_file, apply_route_result

            result = getattr(self, '_parsed_result', None) or parse_route_file(
                self.file
            )
            apply_route_result(self, result)
            if hasattr(self, '_parsed_result'):
                del self._parsed_result
        super().save(*args, **kwargs)

    @property
    def distance_km(self):
        return self.stats.get('distance_km')

    @property
    def elevation_gain_m(self):
        return self.stats.get('elevation_gain_m')

    @property
    def date_start(self):
        if self.manual_date_start:
            return self.manual_date_start
        if self.kind == self.Kind.GROUP:
            return min(
                (route.date_start for route in self.recordings if route.date_start),
                default=None,
            )
        stats = self.parsed_stats or {}
        value = stats.get('date_start') or min(
            stats.get('activity_dates') or [], default=None
        )
        return date.fromisoformat(value) if value else None

    @property
    def date_end(self):
        if self.manual_date_end:
            return self.manual_date_end
        if self.kind == self.Kind.GROUP:
            return max(
                (route.date_end for route in self.recordings if route.date_end),
                default=None,
            )
        stats = self.parsed_stats or {}
        value = stats.get('date_end') or max(
            stats.get('activity_dates') or [], default=None
        )
        return date.fromisoformat(value) if value else None


class AdventureRoute(Orderable):
    page = ParentalKey(
        'adventures.AdventurePage',
        related_name='adventure_routes',
        on_delete=models.CASCADE,
    )
    route = models.ForeignKey(
        Route, related_name='adventure_links', on_delete=models.PROTECT
    )
    panels = [FieldPanel('route')]

    class Meta(Orderable.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=['page', 'route'], name='unique_adventure_route'
            )
        ]


class AdventureIndexPage(Page):
    intro = RichTextField(blank=True)

    content_panels = Page.content_panels + [FieldPanel('intro')]
    parent_page_types = ['wagtailcore.Page']
    subpage_types = ['adventures.AdventurePage']

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['adventure_posts'] = sorted(
            AdventurePage.objects.child_of(self)
            .live()
            .public()
            .prefetch_related('adventure_routes__route__children'),
            key=lambda page: page.effective_date_start or date.min,
            reverse=True,
        )
        return context

    class Meta:
        verbose_name = 'Adventure Index Page'


class AdventurePage(Page):
    date_start = models.DateField(
        null=True,
        blank=True,
        help_text='Optional trip start override. Leave blank to use selected routes.',
    )
    date_end = models.DateField(
        null=True,
        blank=True,
        help_text='Optional trip end override. Leave blank to use selected routes.',
    )
    intro = models.CharField(max_length=500, blank=True)
    header_image = models.ForeignKey(
        'wagtailimages.Image',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    location = models.CharField(max_length=255, blank=True)
    distance_km = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Optional override. Leave blank to use selected routes.',
    )
    elevation_gain_m = models.IntegerField(
        null=True,
        blank=True,
        help_text='Optional override. Leave blank to use selected routes.',
    )
    body = StreamField(standard_body_blocks(), blank=True, use_json_field=True)
    tags = ClusterTaggableManager(through=AdventurePageTag, blank=True)

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['maptiler_api_key'] = settings.MAPTILER_API_KEY
        route_ids = [route.pk for route in self.selected_recordings]
        context['route_urls'] = [
            reverse('adventure-route-geojson', args=[route_id])
            for route_id in route_ids
        ]
        context['has_route'] = bool(context['route_urls'])
        return context

    @cached_property
    def selected_routes(self):
        return [link.route for link in self.adventure_routes.all()]

    @cached_property
    def selected_recordings(self):
        unique = {}
        for route in self.selected_routes:
            for recording in route.recordings:
                unique.setdefault(recording.pk, recording)
        return list(unique.values())

    @property
    def computed_stats(self):
        from adventures.services import aggregate_stats

        stats = [
            route.parsed_stats
            for route in self.selected_recordings
            if route.parsed_stats
        ]
        return aggregate_stats(stats) if stats else {}

    @property
    def activity_type(self):
        types = list(
            dict.fromkeys(
                route.get_activity_type_display() for route in self.selected_recordings
            )
        )
        return ' / '.join(types)

    @property
    def effective_date_start(self):
        return self.date_start or min(
            (route.date_start for route in self.selected_routes if route.date_start),
            default=None,
        )

    @property
    def effective_date_end(self):
        return self.date_end or max(
            (route.date_end for route in self.selected_routes if route.date_end),
            default=None,
        )

    @property
    def effective_distance_km(self):
        if self.distance_km is not None:
            return self.distance_km
        return self.computed_stats.get('distance_km') if self.computed_stats else None

    @property
    def effective_elevation_gain_m(self):
        if self.elevation_gain_m is not None:
            return self.elevation_gain_m
        return (
            self.computed_stats.get('elevation_gain_m') if self.computed_stats else None
        )

    @property
    def date_display(self):
        start = self.effective_date_start
        end = self.effective_date_end
        if not start:
            return ''
        if not end or end == start:
            return start.strftime('%b %-d, %Y')
        if start.year == end.year and start.month == end.month:
            return f'{start.strftime("%b %-d")}–{end.strftime("%-d, %Y")}'
        if start.year == end.year:
            return f'{start.strftime("%b %-d")} – {end.strftime("%b %-d, %Y")}'
        return f'{start.strftime("%b %-d, %Y")} – {end.strftime("%b %-d, %Y")}'

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [FieldPanel('tags')],
            heading='Post Metadata',
        ),
        MultiFieldPanel(
            [
                FieldPanel('location'),
                FieldPanel('date_start'),
                FieldPanel('date_end'),
                FieldPanel('distance_km'),
                FieldPanel('elevation_gain_m'),
            ],
            heading='Trip details and optional overrides',
        ),
        FieldPanel('intro'),
        FieldPanel('header_image'),
        InlinePanel('adventure_routes', label='Routes'),
        InlinePanel('adventure_waypoints', label='Waypoints'),
        FieldPanel('body'),
    ]

    parent_page_types = ['adventures.AdventureIndexPage']
    subpage_types = []

    class Meta:
        verbose_name = 'Adventure Post'
        ordering = ['-date_start']
