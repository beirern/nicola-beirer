from django.conf import settings


def app_version(request):
    return {"app_version": settings.APP_VERSION}


def carto_key(request):
    return {'carto_api_key': settings.CARTO_API_KEY}
