from django.db import migrations


def migrate_gpx_files(apps, schema_editor):
    AdventurePage = apps.get_model('adventures', 'AdventurePage')
    ActivityFile = apps.get_model('adventures', 'ActivityFile')
    for page in AdventurePage.objects.filter(gpx_file__isnull=False).exclude(gpx_file='').order_by('pk'):
        ActivityFile.objects.create(
            page=page,
            file=page.gpx_file,
            file_type='gpx',
            sort_order=0,
        )


def reverse_migrate(apps, schema_editor):
    ActivityFile = apps.get_model('adventures', 'ActivityFile')
    ActivityFile.objects.filter(file_type='gpx').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('adventures', '0003_add_activity_file_and_computed_fields'),
    ]

    operations = [
        migrations.RunPython(migrate_gpx_files, reverse_code=reverse_migrate),
    ]
