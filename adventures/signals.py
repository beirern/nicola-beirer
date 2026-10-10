import threading

from adventures import services


def process_activity_files_on_publish(sender, instance, **kwargs):
    from adventures.models import AdventurePage
    if not isinstance(instance, AdventurePage):
        return
    files = list(instance.activity_files.all())
    current_file_ids = {activity_file.pk for activity_file in files}
    aggregated_file_ids = set((instance.computed_stats or {}).get('source_file_ids', []))
    needs_processing = current_file_ids != aggregated_file_ids or any(
        activity_file.processed_at is None
        or activity_file.parsed_stats is None
        or 'activity_dates' not in activity_file.parsed_stats
        for activity_file in files
    )
    if not needs_processing:
        return

    # Reaggregate when files were removed; only changed or legacy files are parsed.
    t = threading.Thread(
        target=services.process_adventure_files,
        args=(instance,),
        daemon=True,
    )
    t.start()
