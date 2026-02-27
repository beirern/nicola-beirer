"""Parsing and aggregation logic for FIT/GPX activity files."""

import io


def _semicircles_to_degrees(semicircles):
    return semicircles * (180 / 2**31)


def _get_fit_field(frame, field_name):
    for field in frame.fields:
        if field.name == field_name:
            return field.value
    return None


def parse_fit_file(file_obj):
    """
    Parse a FIT file-like object.

    Returns {'stats': {...}, 'gps_points': [[lon, lat, elevation], ...]}
    """
    import fitdecode

    gps_points = []
    session_stats = None

    with fitdecode.FitReader(file_obj) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue

            if frame.name == 'record':
                lat = _get_fit_field(frame, 'position_lat')
                lon = _get_fit_field(frame, 'position_long')
                if lat is None or lon is None:
                    continue

                elevation = _get_fit_field(frame, 'enhanced_altitude')
                if elevation is None:
                    elevation = _get_fit_field(frame, 'altitude') or 0.0

                gps_points.append([
                    round(_semicircles_to_degrees(lon), 7),
                    round(_semicircles_to_degrees(lat), 7),
                    round(float(elevation), 1),
                ])

            elif frame.name == 'session':
                elapsed = _get_fit_field(frame, 'total_elapsed_time') or 0
                moving = _get_fit_field(frame, 'total_timer_time') or elapsed
                max_speed = _get_fit_field(frame, 'max_speed') or 0
                # Cap at 22.2 m/s (80 km/h) to filter GPS artifacts
                if max_speed > 22.2:
                    max_speed = 0

                session_stats = {
                    'distance_km': round((_get_fit_field(frame, 'total_distance') or 0) / 1000, 3),
                    'elevation_gain_m': int(_get_fit_field(frame, 'total_ascent') or 0),
                    'elevation_loss_m': int(_get_fit_field(frame, 'total_descent') or 0),
                    'elapsed_time_s': round(float(elapsed), 1),
                    'moving_time_s': round(float(moving), 1),
                    'calories': int(_get_fit_field(frame, 'total_calories') or 0),
                    'avg_speed_kmh': round((_get_fit_field(frame, 'avg_speed') or 0) * 3.6, 2),
                    'max_speed_kmh': round(float(max_speed) * 3.6, 2),
                }

    if session_stats is None:
        session_stats = {
            'distance_km': 0, 'elevation_gain_m': 0, 'elevation_loss_m': 0,
            'elapsed_time_s': 0, 'moving_time_s': 0, 'calories': 0,
            'avg_speed_kmh': 0, 'max_speed_kmh': 0,
        }

    return {'stats': session_stats, 'gps_points': gps_points}


def parse_gpx_file(file_obj):
    """
    Parse a GPX file-like object.

    Returns {'stats': {...}, 'gps_points': [[lon, lat, elevation], ...]}
    """
    import gpxpy

    content = file_obj.read()
    if isinstance(content, bytes):
        content = content.decode('utf-8')
    gpx = gpxpy.parse(content)

    gps_points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                gps_points.append([
                    round(point.longitude, 7),
                    round(point.latitude, 7),
                    round(float(point.elevation or 0), 1),
                ])

    moving_data = gpx.get_moving_data()
    uphill_downhill = gpx.get_uphill_downhill()

    distance_km = round((moving_data.moving_distance if moving_data else 0) / 1000, 3)
    moving_time_s = round(float(moving_data.moving_time if moving_data else 0), 1)

    elapsed_time_s = 0.0
    for track in gpx.tracks:
        td = track.get_duration()
        if td:
            elapsed_time_s += td

    avg_speed_kmh = 0.0
    if moving_time_s > 0:
        avg_speed_kmh = round(distance_km / moving_time_s * 3600, 2)

    return {
        'stats': {
            'distance_km': distance_km,
            'elevation_gain_m': int(uphill_downhill.uphill if uphill_downhill else 0),
            'elevation_loss_m': int(uphill_downhill.downhill if uphill_downhill else 0),
            'elapsed_time_s': round(elapsed_time_s, 1),
            'moving_time_s': moving_time_s,
            'calories': None,
            'avg_speed_kmh': avg_speed_kmh,
            'max_speed_kmh': 0.0,
        },
        'gps_points': gps_points,
    }


def build_geojson_linestring(gps_points):
    """Build a GeoJSON LineString Feature from [[lon, lat, elev], ...] coords."""
    return {
        'type': 'Feature',
        'geometry': {
            'type': 'LineString',
            'coordinates': gps_points,
        },
        'properties': {},
    }


def merge_geojson_features(features):
    """Wrap a list of GeoJSON Features in a FeatureCollection."""
    return {
        'type': 'FeatureCollection',
        'features': features,
    }


def aggregate_stats(stats_list):
    """Aggregate a list of per-file stats dicts into totals."""
    total_distance_km = sum(s.get('distance_km') or 0 for s in stats_list)
    total_elevation_gain = sum(s.get('elevation_gain_m') or 0 for s in stats_list)
    total_elevation_loss = sum(s.get('elevation_loss_m') or 0 for s in stats_list)
    total_elapsed_time = sum(s.get('elapsed_time_s') or 0 for s in stats_list)
    total_moving_time = sum(s.get('moving_time_s') or 0 for s in stats_list)
    # Only sum calories from files that have it (FIT files); ignore None
    total_calories = sum(
        s.get('calories') or 0 for s in stats_list if s.get('calories') is not None
    )
    max_speed = max((s.get('max_speed_kmh') or 0 for s in stats_list), default=0)

    avg_speed = 0.0
    if total_moving_time > 0:
        avg_speed = round(total_distance_km / total_moving_time * 3600, 2)

    return {
        'distance_km': round(total_distance_km, 3),
        'elevation_gain_m': int(total_elevation_gain),
        'elevation_loss_m': int(total_elevation_loss),
        'elapsed_time_s': round(total_elapsed_time, 1),
        'moving_time_s': round(total_moving_time, 1),
        'calories': int(total_calories),
        'avg_speed_kmh': avg_speed,
        'max_speed_kmh': round(float(max_speed), 2),
    }


def process_adventure_files(adventure_page):
    """
    Process all activity files for an AdventurePage.

    - Parses unprocessed files, saves per-file results.
    - Aggregates stats across all files.
    - Updates adventure_page.computed_stats and merged_route_geojson via queryset
      update to avoid re-triggering the publish signal.
    """
    from django.utils import timezone
    from adventures.models import ActivityFile, AdventurePage as AP

    all_stats = []
    all_features = []

    for activity_file in adventure_page.activity_files.all().order_by('sort_order'):
        if activity_file.processed_at is None:
            with activity_file.file.open('rb') as f:
                raw = f.read()

            if activity_file.file_type == 'fit':
                result = parse_fit_file(io.BytesIO(raw))
            else:
                result = parse_gpx_file(io.BytesIO(raw))

            feature = build_geojson_linestring(result['gps_points'])

            ActivityFile.objects.filter(pk=activity_file.pk).update(
                parsed_stats=result['stats'],
                route_geojson=feature,
                processed_at=timezone.now(),
            )
            activity_file.parsed_stats = result['stats']
            activity_file.route_geojson = feature

        if activity_file.parsed_stats:
            all_stats.append(activity_file.parsed_stats)
        if activity_file.route_geojson:
            all_features.append(activity_file.route_geojson)

    aggregated = aggregate_stats(all_stats) if all_stats else None
    merged = merge_geojson_features(all_features) if all_features else None

    AP.objects.filter(pk=adventure_page.pk).update(
        computed_stats=aggregated,
        merged_route_geojson=merged,
    )
