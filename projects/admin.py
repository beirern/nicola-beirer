from django.contrib import admin
from .models import ResumeProject


@admin.register(ResumeProject)
class ResumeProjectAdmin(admin.ModelAdmin):
    list_display = ('title',)
    search_fields = ('title', 'keywords')
