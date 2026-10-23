"""Parsing and aggregation logic for FIT/GPX activity files."""

import json
import math
import uuid

from django.core.files.base import ContentFile


def _semicircles_to_degrees(semicircles):
    return semicircles * (180 / 2**31)


def _get_fit_field(frame, field_name):
    for field in frame.fields:
        if field.name == field_name:
            return field.value
    return None


def _fit_activity_dates(records):
    """Return UTC dates with movement in timestamped FIT records."""
    dates = set()
    for previous, current in zip(records, records[1:]):
        previous_time, previous_speed, previous_position = previous
        current_time, current_speed, current_position = current
        if not previous_time or not current_time or current_time <= previous_time:
            continue
        seconds = (current_time - previous_time).total_seconds()
        if (
            seconds > 3600
        ):  # A recording gap is not evidence of activity between its endpoints.
            continue

        speeds = [
            speed for speed in (previous_speed, current_speed) if speed is not None
        ]
        if speeds:
            moving = max(speeds) > 1 / 3.6  # 1 km/h, matching gpxpy's default
        elif previous_position and current_position:
            lat1, lon1 = previous_position
            lat2, lon2 = current_position
            latitude_delta = math.radians(lat2 - lat1)
            longitude_delta = math.radians(lon2 - lon1)
            arc = (
                math.sin(latitude_delta / 2) ** 2
                + math.cos(math.radians(lat1))
                * math.cos(math.radians(lat2))
                * math.sin(longitude_delta / 2) ** 2
            )
            distance_m = 6371000 * 2 * math.atan2(math.sqrt(arc), math.sqrt(1 - arc))
            moving = distance_m / seconds > 1 / 3.6
        else:
            moving = False

        if moving:
            dates.update(
                (previous_time.date().isoformat(), current_time.date().isoformat())
            )
    return sorted(dates)


def _gpx_activity_dates(gpx):
    """Return dates with moving track points, excluding unrecorded rest days."""
    dates = set()
    for track in gpx.tracks:
        for segment in track.segments:
            for previous, point in zip(segment.points, segment.points[1:]):
                if not previous.time or not point.time:
                    continue
                seconds = (point.time - previous.time).total_seconds()
                if seconds <= 0 or seconds > 3600:
                    continue
                if point.elevation and previous.elevation:
                    distance = point.distance_3d(previous)
                else:
                    distance = point.distance_2d(previous)
                if distance is not None and distance / seconds > 1 / 3.6:
                    dates.update(
                        (
                            previous.time.date().isoformat(),
                            point.time.date().isoformat(),
                        )
                    )
    return sorted(dates)


def parse_fit_file(file_obj):
    """
    Parse a FIT file-like object.

    Returns {'stats': {...}, 'gps_points': [[lon, lat, elevation], ...]}
    """
    import fitdecode

    gps_points = []
    session_stats = None
    records = []

    with fitdecode.FitReader(file_obj) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue

            if frame.name == 'record':
                timestamp = _get_fit_field(frame, 'timestamp')
                speed = _get_fit_field(frame, 'enhanced_speed')
                if speed is None:
                    speed = _get_fit_field(frame, 'speed')
                lat = _get_fit_field(frame, 'position_lat')
                lon = _get_fit_field(frame, 'position_long')
                position = None
                if lat is not None and lon is not None:
                    position = (
                        _semicircles_to_degrees(lat),
                        _semicircles_to_degrees(lon),
                    )
                records.append((timestamp, speed, position))
                if lat is None or lon is None:
                    continue

                elevation = _get_fit_field(frame, 'enhanced_altitude')
                if elevation is None:
                    elevation = _get_fit_field(frame, 'altitude') or 0.0

                gps_points.append(
                    [
                        round(_semicircles_to_degrees(lon), 7),
                        round(_semicircles_to_degrees(lat), 7),
                        round(float(elevation), 1),
                    ]
                )

            elif frame.name == 'session':
                elapsed = _get_fit_field(frame, 'total_elapsed_time') or 0
                moving = _get_fit_field(frame, 'total_timer_time') or elapsed
                max_speed = _get_fit_field(frame, 'max_speed') or 0
                # Cap at 22.2 m/s (80 km/h) to filter GPS artifacts
                if max_speed > 22.2:
                    max_speed = 0

                session_stats = {
                    'distance_km': round(
                        (_get_fit_field(frame, 'total_distance') or 0) / 1000, 3
                    ),
                    'elevation_gain_m': int(_get_fit_field(frame, 'total_ascent') or 0),
                    'elevation_loss_m': int(
                        _get_fit_field(frame, 'total_descent') or 0
                    ),
                    'elapsed_time_s': round(float(elapsed), 1),
                    'moving_time_s': round(float(moving), 1),
                    'calories': int(_get_fit_field(frame, 'total_calories') or 0),
                    'avg_speed_kmh': round(
                        (_get_fit_field(frame, 'avg_speed') or 0) * 3.6, 2
                    ),
                    'max_speed_kmh': round(float(max_speed) * 3.6, 2),
                    'activity_dates': [],
                }

    if session_stats is None:
        session_stats = {
            'distance_km': 0,
            'elevation_gain_m': 0,
            'elevation_loss_m': 0,
            'elapsed_time_s': 0,
            'moving_time_s': 0,
            'calories': 0,
            'avg_speed_kmh': 0,
            'max_speed_kmh': 0,
            'activity_dates': [],
        }

    session_stats['activity_dates'] = _fit_activity_dates(records)
    timestamps = [record[0].date().isoformat() for record in records if record[0]]
    session_stats['date_start'] = min(timestamps, default=None)
    session_stats['date_end'] = max(timestamps, default=None)

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
                gps_points.append(
                    [
                        round(point.longitude, 7),
                        round(point.latitude, 7),
                        round(float(point.elevation or 0), 1),
                    ]
                )

    timestamps = [
        point.time.date().isoformat()
        for track in gpx.tracks
        for segment in track.segments
        for point in segment.points
        if point.time
    ]
    features = [
        build_geojson_linestring(
            [
                [
                    round(p.longitude, 7),
                    round(p.latitude, 7),
                    round(float(p.elevation or 0), 1),
                ]
                for p in segment.points
            ]
        )
        for track in gpx.tracks
        for segment in track.segments
        if len(segment.points) >= 2
    ]

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
            'activity_dates': _gpx_activity_dates(gpx),
            'date_start': min(timestamps, default=None),
            'date_end': max(timestamps, default=None),
        },
        'gps_points': gps_points,
        'features': features,
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


def parse_route_file(file):
    """Validate an upload before the admin saves any changes."""
    file.open('rb')
    try:
        file.seek(0)
        result = (
            parse_fit_file(file)
            if file.name.lower().endswith('.fit')
            else parse_gpx_file(file)
        )
        points = result['gps_points']
        if any(
            not all(math.isfinite(value) for value in point)
            or not -180 <= point[0] <= 180
            or not -90 <= point[1] <= 90
            for point in points
        ):
            raise ValueError('The recording contains invalid GPS coordinates.')
        if len(points) < 2:
            raise ValueError('The recording has fewer than two GPS points.')
        return result
    finally:
        file.seek(0)


def apply_route_result(route, result):
    points = result['gps_points']
    route.parsed_stats = result['stats']
    route.min_longitude = min(point[0] for point in points)
    route.min_latitude = min(point[1] for point in points)
    route.max_longitude = max(point[0] for point in points)
    route.max_latitude = max(point[1] for point in points)
    payload = merge_geojson_features(
        result.get('features') or [build_geojson_linestring(points)]
    )
    route.geojson_file.save(
        f'{uuid.uuid4().hex}.geojson',
        ContentFile(json.dumps(payload, separators=(',', ':')).encode('utf-8')),
        save=False,
    )


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

    # Old parsed stats have no activity_dates until they are explicitly reparsed.
    # Suppress daily averages if any moving time or distance lacks a day count.
    complete_dates = all(
        not (stats.get('moving_time_s') or stats.get('distance_km'))
        or stats.get('activity_dates')
        for stats in stats_list
    )
    active_dates = set()
    if complete_dates:
        for stats in stats_list:
            active_dates.update(stats.get('activity_dates') or [])
    active_days = len(active_dates) if active_dates else None

    return {
        'distance_km': round(total_distance_km, 3),
        'elevation_gain_m': int(total_elevation_gain),
        'elevation_loss_m': int(total_elevation_loss),
        'elapsed_time_s': round(total_elapsed_time, 1),
        'moving_time_s': round(total_moving_time, 1),
        'calories': int(total_calories),
        'avg_speed_kmh': avg_speed,
        'max_speed_kmh': round(float(max_speed), 2),
        'active_days': active_days,
        'avg_hours_per_active_day': round(total_moving_time / 3600 / active_days, 1)
        if active_days
        else None,
        'avg_distance_km_per_active_day': round(total_distance_km / active_days, 1)
        if active_days
        else None,
    }
