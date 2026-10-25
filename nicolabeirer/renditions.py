"""Renditions the site shows, built when content is saved rather than on a visitor's first view.

The filter specs mirror the ``{% image %}`` tags in the templates;
``nicolabeirer.tests`` checks that none of them drift apart.
"""

import logging

from django.dispatch import receiver
from wagtail.signals import page_published

logger = logging.getLogger(__name__)

WAYPOINT_PREVIEW_FILTER = 'fill-120x150'
WAYPOINT_PHOTO_FILTER = 'width-1200'

WAYPOINT_PHOTO = (WAYPOINT_PREVIEW_FILTER, WAYPOINT_PHOTO_FILTER)
GALLERY_PHOTO = ('fill-400x400', 'fill-200x200')
ALBUM_COVER = ('fill-600x400', 'fill-80x80')
ADVENTURE_HEADER = ('width-1200', 'fill-200x140')
BLOG_HEADER = ('width-1200',)
BODY_IMAGE = ('width-800',)
CAROUSEL_IMAGE = ('width-1000',)

ALL_SPECS = frozenset(
    WAYPOINT_PHOTO + GALLERY_PHOTO + ALBUM_COVER + ADVENTURE_HEADER
    + BLOG_HEADER + BODY_IMAGE + CAROUSEL_IMAGE
)


def warm(image, specs):
    """Build each rendition now; a source file that cannot be read is logged, not raised."""
    for spec in specs:
        try:
            image.get_rendition(spec)
        except OSError:
            logger.warning('Could not build %s rendition for image %s', spec, image.pk)


def body_images(body):
    for block in body:
        if block.block_type == 'image':
            yield block.value['image'], BODY_IMAGE
        elif block.block_type == 'carousel':
            for item in block.value['images']:
                yield item['image'], CAROUSEL_IMAGE


def page_images(page):
    """Yield (image, specs) for the images a page's own fields show."""
    from adventures.models import AdventurePage
    from blog.models import BlogPage
    from gallery.models import GalleryAlbumPage

    if isinstance(page, AdventurePage):
        yield page.header_image, ADVENTURE_HEADER
        yield from body_images(page.body)
    elif isinstance(page, BlogPage):
        yield page.header_image, BLOG_HEADER
        yield from body_images(page.body)
    elif isinstance(page, GalleryAlbumPage):
        yield page.cover_image, ALBUM_COVER


def all_images():
    """Yield (image, specs) for every image the public pages show."""
    from adventures.models import AdventurePage, WaypointPhoto
    from blog.models import BlogPage
    from gallery.models import GalleryAlbumPage, GalleryPhoto

    for photo in WaypointPhoto.objects.select_related('image'):
        yield photo.image, WAYPOINT_PHOTO
    for photo in GalleryPhoto.objects.select_related('image'):
        yield photo.image, GALLERY_PHOTO
    for model in (AdventurePage, BlogPage, GalleryAlbumPage):
        for page in model.objects.live():
            yield from page_images(page)


@receiver(page_published)
def warm_page_renditions(sender, instance, **kwargs):
    for image, specs in page_images(instance):
        if image is not None:
            warm(image, specs)
