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


class AdventureIndexPage(Page):
    intro = RichTextField(blank=True)

    content_panels = Page.content_panels + [FieldPanel('intro')]
    parent_page_types = ['wagtailcore.Page']
    subpage_types = ['adventures.AdventurePage']

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['adventure_posts'] = AdventurePage.objects.child_of(self).live().order_by('-date')
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

    date = models.DateField(default=datetime.date.today)
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
    distance_km = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    elevation_gain_m = models.IntegerField(null=True, blank=True)
    gpx_file = models.FileField(upload_to='gpx/', null=True, blank=True)
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

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [FieldPanel('date'), FieldPanel('tags'), FieldPanel('activity_type')],
            heading='Post Metadata',
        ),
        MultiFieldPanel(
            [FieldPanel('location'), FieldPanel('distance_km'), FieldPanel('elevation_gain_m')],
            heading='Trip Stats',
        ),
        FieldPanel('intro'),
        FieldPanel('header_image'),
        FieldPanel('gpx_file'),
        InlinePanel('waypoints', label='Waypoints'),
        FieldPanel('body'),
    ]

    parent_page_types = ['adventures.AdventureIndexPage']
    subpage_types = []

    class Meta:
        verbose_name = 'Adventure Post'
        ordering = ['-date']
