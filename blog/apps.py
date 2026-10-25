from django.apps import AppConfig


class BlogConfig(AppConfig):
    name = "blog"

    def ready(self):
        from nicolabeirer import renditions  # noqa: F401  connects the page_published receiver
