from django import template

from gallery.models import GalleryAlbumPage, GalleryPhoto

register = template.Library()


@register.simple_tag
def get_adventure_gallery(adventure_page):
    """Return gallery albums linked to this adventure page."""
    return GalleryAlbumPage.objects.live().filter(adventure_page=adventure_page)


@register.simple_tag
def get_adventure_photos(adventure_page):
    """Return individual gallery photos linked to this adventure page."""
    return GalleryPhoto.objects.filter(
        adventure_page=adventure_page,
        page__live=True,
    ).select_related('image', 'page')
