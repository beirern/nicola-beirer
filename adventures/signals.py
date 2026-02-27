import threading

from adventures import services


def process_activity_files_on_publish(sender, instance, **kwargs):
    from adventures.models import AdventurePage
    if not isinstance(instance, AdventurePage):
        return
    if instance.activity_files.filter(processed_at__isnull=True).exists():
        t = threading.Thread(
            target=services.process_adventure_files,
            args=(instance,),
            daemon=True,
        )
        t.start()
