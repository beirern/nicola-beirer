from django import template

register = template.Library()


@register.filter
def duration(seconds):
    """Format seconds as 'Xh MMm'. Returns '—' if falsy."""
    if not seconds:
        return '—'
    h, remainder = divmod(int(seconds), 3600)
    m = remainder // 60
    return f'{h}h {m:02d}m'
