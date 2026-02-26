from django.contrib import admin
from .models import ResumeProject


@admin.register(ResumeProject)
class ResumeProjectAdmin(admin.ModelAdmin):
    list_display = ('title', 'live_url', 'github_url')
    search_fields = ('title', 'keywords')
