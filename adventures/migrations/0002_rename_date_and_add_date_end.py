import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('adventures', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='adventurepage',
            old_name='date',
            new_name='date_start',
        ),
        migrations.AddField(
            model_name='adventurepage',
            name='date_end',
            field=models.DateField(blank=True, null=True),
        ),
    ]
