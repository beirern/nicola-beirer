import django.db.models.deletion
import modelcluster.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('adventures', '0002_rename_date_and_add_date_end'),
    ]

    operations = [
        migrations.CreateModel(
            name='ActivityFile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sort_order', models.IntegerField(blank=True, editable=False, null=True)),
                ('file', models.FileField(upload_to='activity_files/')),
                ('file_type', models.CharField(
                    choices=[('gpx', 'GPX'), ('fit', 'FIT')],
                    default='gpx',
                    editable=False,
                    max_length=3,
                )),
                ('parsed_stats', models.JSONField(blank=True, null=True)),
                ('route_geojson', models.JSONField(blank=True, null=True)),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
                ('page', modelcluster.fields.ParentalKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='activity_files',
                    to='adventures.adventurepage',
                )),
            ],
            options={
                'ordering': ['sort_order'],
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='adventurepage',
            name='computed_stats',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='adventurepage',
            name='merged_route_geojson',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
