import django.core.validators
import django.db.models.deletion
import modelcluster.fields
from decimal import Decimal
from django.db import migrations, models


def move_waypoints(apps, schema_editor):
    alias = schema_editor.connection.alias
    Waypoint = apps.get_model('adventures', 'Waypoint')
    Link = apps.get_model('adventures', 'AdventureWaypoint')
    RouteLink = apps.get_model('adventures', 'AdventureRoute')
    Route = apps.get_model('adventures', 'Route')
    Revision = apps.get_model('wagtailcore', 'Revision')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    content_type = ContentType.objects.using(alias).filter(
        app_label='adventures', model='adventurepage'
    ).first()

    def eligible_route(page_id):
        route_ids = list(RouteLink.objects.using(alias).filter(page_id=page_id).values_list('route_id', flat=True))
        if len(route_ids) != 1:
            return None
        route = Route.objects.using(alias).filter(pk=route_ids[0]).first()
        if route and (route.kind == 'group' or route.parent_route_id is None):
            return route.pk
        return None

    route_by_page = {}
    current = {}
    for waypoint in Waypoint.objects.using(alias).all().iterator():
        route_id = route_by_page.setdefault(waypoint.page_id, eligible_route(waypoint.page_id))
        if route_id:
            Waypoint.objects.using(alias).filter(pk=waypoint.pk).update(route_id=route_id)
        link = Link.objects.using(alias).create(
            page_id=waypoint.page_id, waypoint_id=waypoint.pk, sort_order=waypoint.sort_order
        )
        current[(waypoint.page_id, waypoint.pk)] = (waypoint, link)

    if not content_type:
        return
    historical = {}
    for revision in Revision.objects.using(alias).filter(content_type_id=content_type.pk).iterator():
        content = revision.content
        if 'waypoints' not in content:
            continue
        page_id = int(revision.object_id)
        route_id = route_by_page.setdefault(page_id, eligible_route(page_id))
        converted = []
        for item in content['waypoints']:
            fields = (item.get('name', ''), item.get('description', ''),
                      Decimal(str(item.get('latitude'))), Decimal(str(item.get('longitude'))))
            if item.get('pk') and (page_id, item['pk']) in current:
                waypoint, link = current[(page_id, item['pk'])]
                saved = (waypoint.name, waypoint.description,
                         waypoint.latitude, waypoint.longitude)
                if fields == saved:
                    converted.append({'pk': link.pk, 'page': page_id,
                                      'waypoint': waypoint.pk, 'sort_order': item.get('sort_order')})
                    continue
            key = (page_id, item.get('pk'), fields)
            if key not in historical:
                historical[key] = Waypoint.objects.using(alias).create(
                    name=fields[0], description=fields[1], latitude=item['latitude'],
                    longitude=item['longitude'], route_id=route_id, is_public=False,
                    page_id=page_id, sort_order=item.get('sort_order'),
                ).pk
            converted.append({'pk': None, 'page': page_id,
                              'waypoint': historical[key], 'sort_order': item.get('sort_order')})
        content['adventure_waypoints'] = converted
        del content['waypoints']
        Revision.objects.using(alias).filter(pk=revision.pk).update(content=content)


class Migration(migrations.Migration):
    dependencies = [
        ('adventures', '0014_route_groups'),
        ('wagtailimages', '0027_image_description'),
    ]

    operations = [
        migrations.AddField(
            model_name='waypoint', name='is_public',
            field=models.BooleanField(default=False, verbose_name='Show on public map'),
        ),
        migrations.AddField(
            model_name='waypoint', name='route',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='waypoints', to='adventures.route'),
        ),
        migrations.CreateModel(
            name='AdventureWaypoint',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sort_order', models.IntegerField(blank=True, editable=False, null=True)),
                ('page', modelcluster.fields.ParentalKey(on_delete=django.db.models.deletion.CASCADE,
                                                       related_name='adventure_waypoints', to='adventures.adventurepage')),
                ('waypoint', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                               related_name='adventure_links', to='adventures.waypoint')),
            ],
            options={'ordering': ['sort_order'], 'abstract': False},
        ),
        migrations.CreateModel(
            name='WaypointPhoto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sort_order', models.IntegerField(blank=True, editable=False, null=True)),
                ('caption', models.CharField(blank=True, max_length=500)),
                ('image', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                            related_name='+', to='wagtailimages.image')),
                ('waypoint', modelcluster.fields.ParentalKey(on_delete=django.db.models.deletion.CASCADE,
                                                             related_name='photos', to='adventures.waypoint')),
            ],
            options={'ordering': ['sort_order'], 'abstract': False},
        ),
        migrations.RunPython(move_waypoints, migrations.RunPython.noop),
        migrations.RemoveField(model_name='waypoint', name='page'),
        migrations.RemoveField(model_name='waypoint', name='sort_order'),
        migrations.AlterModelOptions(name='waypoint', options={}),
        migrations.AlterField(
            model_name='waypoint', name='latitude',
            field=models.DecimalField(decimal_places=6, max_digits=9, validators=[
                django.core.validators.MinValueValidator(-90), django.core.validators.MaxValueValidator(90)]),
        ),
        migrations.AlterField(
            model_name='waypoint', name='longitude',
            field=models.DecimalField(decimal_places=6, max_digits=9, validators=[
                django.core.validators.MinValueValidator(-180), django.core.validators.MaxValueValidator(180)]),
        ),
    ]
