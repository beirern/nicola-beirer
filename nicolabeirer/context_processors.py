from django.conf import settings


def app_version(request):
    return {"app_version": settings.APP_VERSION}


def maptiler_key(request):
    return {'maptiler_api_key': settings.MAPTILER_API_KEY}
