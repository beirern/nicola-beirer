import datetime

from django.db import models
from modelcluster.contrib.taggit import ClusterTaggableManager
from modelcluster.fields import ParentalKey
from taggit.models import TaggedItemBase
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel
from wagtail.blocks import RichTextBlock
from wagtail.embeds.blocks import EmbedBlock
from wagtail.fields import RichTextField, StreamField
from wagtail.models import Orderable, Page

from blog.models import HeadingBlock, ImageBlock


class AdventurePageTag(TaggedItemBase):
    content_object = ParentalKey(
        'adventures.AdventurePage',
        related_name='tagged_items',
        on_delete=models.CASCADE,
    )


class Waypoint(Orderable):
    page = ParentalKey(
        'adventures.AdventurePage',
        related_name='waypoints',
        on_delete=models.CASCADE,
    )
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=500, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)

    panels = [
        FieldPanel('name'),
        FieldPanel('description'),
        FieldPanel('latitude'),
        FieldPanel('longitude'),
    ]

    def __str__(self):
        return self.name


class ActivityFile(Orderable):
    page = ParentalKey(
        'adventures.AdventurePage',
        related_name='activity_files',
        on_delete=models.CASCADE,
    )
    file = models.FileField(upload_to='activity_files/')
    file_type = models.CharField(
        max_length=3,
        choices=[('gpx', 'GPX'), ('fit', 'FIT')],
        editable=False,
        default='gpx',
    )
    parsed_stats = models.JSONField(null=True, blank=True)
    route_geojson = models.JSONField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    panels = [FieldPanel('file')]

    def save(self, *args, **kwargs):
        if self.file and not self.pk:
            name = str(self.file)
            if '.' in name:
                ext = name.rsplit('.', 1)[-1].lower()
                if ext in ('fit', 'gpx'):
                    self.file_type = ext
        super().save(*args, **kwargs)

    def __str__(self):
        return str(self.file)


class AdventureIndexPage(Page):
    intro = RichTextField(blank=True)

    content_panels = Page.content_panels + [FieldPanel('intro')]
    parent_page_types = ['wagtailcore.Page']
    subpage_types = ['adventures.AdventurePage']

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['adventure_posts'] = AdventurePage.objects.child_of(self).live().order_by('-date_start')
        return context

    class Meta:
        verbose_name = 'Adventure Index Page'


class AdventurePage(Page):
    class ActivityType(models.TextChoices):
        HIKING = 'hiking', 'Hiking'
        CYCLING = 'cycling', 'Cycling'
        RUNNING = 'running', 'Running'
        SKIING = 'skiing', 'Skiing'
        CLIMBING = 'climbing', 'Climbing'
        KAYAKING = 'kayaking', 'Kayaking'
        SAILING = 'sailing', 'Sailing'
        OTHER = 'other', 'Other'

    date_start = models.DateField(default=datetime.date.today)
    date_end = models.DateField(null=True, blank=True)
    intro = models.CharField(max_length=500, blank=True)
    header_image = models.ForeignKey(
        'wagtailimages.Image',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    activity_type = models.CharField(
        max_length=20,
        choices=ActivityType.choices,
        default=ActivityType.HIKING,
    )
    location = models.CharField(max_length=255, blank=True)
    distance_km = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True,
        help_text='Manual override. Leave blank to use value computed from uploaded activity files.',
    )
    elevation_gain_m = models.IntegerField(
        null=True, blank=True,
        help_text='Manual override. Leave blank to use value computed from uploaded activity files.',
    )
    computed_stats = models.JSONField(null=True, blank=True)
    merged_route_geojson = models.JSONField(null=True, blank=True)
    body = StreamField([
        ('heading', HeadingBlock()),
        ('paragraph', RichTextBlock(
            features=['bold', 'italic', 'link', 'ol', 'ul', 'blockquote'],
            template='blog/blocks/paragraph_block.html',
        )),
        ('image', ImageBlock()),
        ('video', EmbedBlock(
            help_text='Paste a YouTube or Vimeo URL',
            template='blog/blocks/video_block.html',
            icon='media',
            label='Video Embed',
        )),
    ], blank=True, use_json_field=True)
    tags = ClusterTaggableManager(through=AdventurePageTag, blank=True)

    @property
    def effective_distance_km(self):
        if self.distance_km is not None:
            return self.distance_km
        return self.computed_stats.get('distance_km') if self.computed_stats else None

    @property
    def effective_elevation_gain_m(self):
        if self.elevation_gain_m is not None:
            return self.elevation_gain_m
        return self.computed_stats.get('elevation_gain_m') if self.computed_stats else None

    @property
    def date_display(self):
        start = self.date_start
        end = self.date_end
        if not end or end == start:
            return start.strftime('%b %-d, %Y')
        if start.year == end.year and start.month == end.month:
            return f"{start.strftime('%b %-d')}–{end.strftime('%-d, %Y')}"
        if start.year == end.year:
            return f"{start.strftime('%b %-d')} – {end.strftime('%b %-d, %Y')}"
        return f"{start.strftime('%b %-d, %Y')} – {end.strftime('%b %-d, %Y')}"

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [FieldPanel('date_start'), FieldPanel('date_end'), FieldPanel('tags'), FieldPanel('activity_type')],
            heading='Post Metadata',
        ),
        MultiFieldPanel(
            [FieldPanel('location'), FieldPanel('distance_km'), FieldPanel('elevation_gain_m')],
            heading='Trip Stats',
        ),
        FieldPanel('intro'),
        FieldPanel('header_image'),
        InlinePanel('activity_files', label='Activity Files (.fit or .gpx)'),
        InlinePanel('waypoints', label='Waypoints'),
        FieldPanel('body'),
    ]

    parent_page_types = ['adventures.AdventureIndexPage']
    subpage_types = []

    class Meta:
        verbose_name = 'Adventure Post'
        ordering = ['-date_start']
