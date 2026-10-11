from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.documents import urls as wagtaildocs_urls

from adventures.views import route_geojson
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('admin/', admin.site.urls),
    path('projects/', include('projects.urls')),
    path('routes/<int:route_id>/geojson/', route_geojson, name='adventure-route-geojson'),
    path('cms/', include(wagtailadmin_urls)),
    path('documents/', include(wagtaildocs_urls)),
    path('', include(wagtail_urls)),  # catch-all, must be last
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
