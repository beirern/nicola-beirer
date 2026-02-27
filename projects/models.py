from django.db import models


class ResumeProject(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    features = models.JSONField(default=list)
    keywords = models.JSONField(default=list)
    links = models.JSONField(default=list, help_text='List of {"label": "...", "url": "..."} objects')

    class Meta:
        ordering = ['title']
        verbose_name = 'Resume Project'
        verbose_name_plural = 'Resume Projects'

    def __str__(self):
        return self.title
