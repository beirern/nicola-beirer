from django.apps import AppConfig


class AdventuresConfig(AppConfig):
    name = "adventures"

    def ready(self):
        from wagtail.signals import page_published
        from adventures.signals import process_activity_files_on_publish
        page_published.connect(process_activity_files_on_publish)
