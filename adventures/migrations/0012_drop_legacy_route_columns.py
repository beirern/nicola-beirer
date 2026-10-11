from django.db import migrations


def drop_legacy_route_columns(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM adventures_activityfile WHERE route_id IS NULL')
        unlinked_files = cursor.fetchone()[0]
    if unlinked_files:
        raise RuntimeError(
            f'{unlinked_files} activity files still lack a Route; run '
            'reprocess_adventure_routes before dropping legacy geometry.'
        )

    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT COUNT(*) FROM adventures_adventurepage AS page '
            'WHERE page.merged_route_geojson IS NOT NULL '
            'AND NOT EXISTS ('
            'SELECT 1 FROM adventures_activityfile AS activity '
            'WHERE activity.page_id = page.page_ptr_id AND activity.route_id IS NOT NULL'
            ')'
        )
        pages_without_routes = cursor.fetchone()[0]
    if pages_without_routes:
        raise RuntimeError(
            f'{pages_without_routes} adventure pages still have legacy geometry '
            'but no linked Route; inspect them before dropping it.'
        )

    for table, column in (
        ('adventures_activityfile', 'route_geojson'),
        ('adventures_adventurepage', 'merged_route_geojson'),
    ):
        with connection.cursor() as cursor:
            present = any(
                field.name == column
                for field in connection.introspection.get_table_description(cursor, table)
            )
        if present:
            schema_editor.execute(
                f'ALTER TABLE {schema_editor.quote_name(table)} '
                f'DROP COLUMN {schema_editor.quote_name(column)}'
            )


class Migration(migrations.Migration):
    dependencies = [
        ('adventures', '0011_remove_activityfile_route_geojson_and_more'),
    ]

    operations = [migrations.RunPython(drop_legacy_route_columns)]
