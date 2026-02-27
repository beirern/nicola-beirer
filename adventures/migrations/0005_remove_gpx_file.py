from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('adventures', '0004_migrate_gpx_file_data'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='adventurepage',
            name='gpx_file',
        ),
    ]
