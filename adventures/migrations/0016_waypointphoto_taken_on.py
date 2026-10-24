from django.db import migrations, models


def fill_taken_on(apps, schema_editor):
    from adventures.models import photo_taken_on

    WaypointPhoto = apps.get_model('adventures', 'WaypointPhoto')
    for photo in WaypointPhoto.objects.select_related('image').filter(taken_on__isnull=True):
        taken_on = photo_taken_on(photo.image)
        if taken_on:
            WaypointPhoto.objects.filter(pk=photo.pk).update(taken_on=taken_on)


class Migration(migrations.Migration):

    dependencies = [
        ('adventures', '0015_waypoint_photo_stops'),
        ('wagtailimages', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='waypointphoto',
            name='taken_on',
            field=models.DateField(blank=True, help_text='Shown before the caption. Filled from the photo when it has a capture date.', null=True),
        ),
        migrations.RunPython(fill_taken_on, migrations.RunPython.noop),
    ]
