from django.db import models
from modelcluster.fields import ParentalKey
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel
from wagtail.fields import RichTextField
from wagtail.models import Orderable, Page


class GalleryIndexPage(Page):
    intro = RichTextField(blank=True)

    content_panels = Page.content_panels + [FieldPanel('intro')]
    parent_page_types = ['wagtailcore.Page']
    subpage_types = ['gallery.GalleryAlbumPage']

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['albums'] = (
            GalleryAlbumPage.objects.child_of(self)
            .live()
            .order_by('-date')
        )
        return context

    class Meta:
        verbose_name = 'Gallery Index Page'


class GalleryAlbumPage(Page):
    description = models.TextField(blank=True)
    date = models.DateField()
    cover_image = models.ForeignKey(
        'wagtailimages.Image',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    adventure_page = models.ForeignKey(
        'adventures.AdventurePage',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='gallery_albums',
    )

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [FieldPanel('date'), FieldPanel('description')],
            heading='Album Details',
        ),
        FieldPanel('cover_image'),
        FieldPanel('adventure_page'),
        InlinePanel('photos', label='Photos'),
    ]

    parent_page_types = ['gallery.GalleryIndexPage']
    subpage_types = []

    @property
    def photo_count(self):
        return self.photos.count()

    class Meta:
        verbose_name = 'Gallery Album'
        ordering = ['-date']


class PhotoSource(models.TextChoices):
    FACEBOOK = 'facebook', 'Facebook'
    INSTAGRAM = 'instagram', 'Instagram'
    CAMERA = 'camera', 'Camera'
    PHONE = 'phone', 'Phone'
    OTHER = 'other', 'Other'


class GalleryPhoto(Orderable):
    page = ParentalKey(
        'gallery.GalleryAlbumPage',
        related_name='photos',
        on_delete=models.CASCADE,
    )
    image = models.ForeignKey(
        'wagtailimages.Image',
        on_delete=models.CASCADE,
        related_name='+',
    )
    caption = models.CharField(max_length=500, blank=True)
    date_taken = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=255, blank=True)
    source = models.CharField(
        max_length=20,
        choices=PhotoSource.choices,
        default=PhotoSource.OTHER,
    )
    adventure_page = models.ForeignKey(
        'adventures.AdventurePage',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='gallery_photos',
    )

    panels = [
        FieldPanel('image'),
        FieldPanel('caption'),
        FieldPanel('date_taken'),
        FieldPanel('location'),
        FieldPanel('source'),
        FieldPanel('adventure_page'),
    ]

    def __str__(self):
        return self.caption or f"Photo {self.sort_order}"
