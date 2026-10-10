"""Polyline distance, time, and corridor offsets."""

from __future__ import annotations

import math
from bisect import bisect_right

EARTH_MILES = 3958.7613


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_MILES * math.asin(min(1.0, math.sqrt(h)))


def cumulative_miles(points: list[tuple[float, float]]) -> list[float]:
    totals = [0.0]
    for start, end in zip(points, points[1:]):
        totals.append(totals[-1] + haversine_miles(start, end))
    return totals


def decode_polyline(encoded: str, precision: int = 6) -> list[tuple[float, float]]:
    """Decode a Valhalla polyline (precision 6) into (lat, lon) pairs."""
    factor = 10**precision
    points: list[tuple[float, float]] = []
    index = 0
    lat = 0
    lon = 0
    length = len(encoded)
    while index < length:
        delta_lat, index = _next_delta(encoded, index)
        delta_lon, index = _next_delta(encoded, index)
        lat += delta_lat
        lon += delta_lon
        points.append((lat / factor, lon / factor))
    return points


def encode_polyline(points: list[tuple[float, float]], precision: int = 6) -> str:
    factor = 10**precision
    output: list[str] = []
    last_lat = 0
    last_lon = 0
    for lat, lon in points:
        ilat = int(round(lat * factor))
        ilon = int(round(lon * factor))
        output.append(_encode_value(ilat - last_lat))
        output.append(_encode_value(ilon - last_lon))
        last_lat, last_lon = ilat, ilon
    return "".join(output)


def vertex_times(
    points: list[tuple[float, float]],
    maneuvers: list[dict],
    duration_sec: float,
) -> list[float]:
    """Seconds from departure at each shape vertex, using maneuver times.

    Time inside a maneuver follows distance along that maneuver, so a slow
    stretch is not treated as the same speed as the rest of the trip.
    The last vertex is scaled to the route duration.
    """
    count = len(points)
    if count == 0:
        return []
    if count == 1:
        return [0.0]

    cumulative = cumulative_miles(points)
    times: list[float | None] = [None] * count
    elapsed = 0.0
    for maneuver in maneuvers:
        begin = _clamp_index(maneuver.get("begin_shape_index", 0), count)
        end = _clamp_index(maneuver.get("end_shape_index", begin), count)
        if end < begin:
            begin, end = end, begin
        segment_time = float(maneuver.get("time") or 0)
        span = cumulative[end] - cumulative[begin]
        for index in range(begin, end + 1):
            fraction = 0.0 if span <= 1e-9 else (cumulative[index] - cumulative[begin]) / span
            times[index] = elapsed + fraction * segment_time
        elapsed += segment_time

    if times[0] is None:
        times[0] = 0.0
    if times[-1] is None:
        times[-1] = float(duration_sec)
    _fill_time_gaps(times, cumulative)

    filled = [float(value) for value in times]
    end_time = filled[-1]
    if end_time > 1 and duration_sec >= 0 and abs(end_time - duration_sec) > 1:
        scale = duration_sec / end_time
        filled = [value * scale for value in filled]
    return filled


def interpolate(
    points: list[tuple[float, float]],
    cumulative: list[float],
    times: list[float],
    mile: float,
) -> tuple[float, float, float]:
    """Lat, lon, and seconds-from-start at a distance along the polyline."""
    if mile <= 0:
        return points[0][0], points[0][1], times[0]
    if mile >= cumulative[-1]:
        return points[-1][0], points[-1][1], times[-1]
    index = bisect_right(cumulative, mile)
    if index <= 0:
        index = 1
    if index >= len(points):
        index = len(points) - 1
    span = cumulative[index] - cumulative[index - 1]
    fraction = 0.0 if span <= 1e-9 else (mile - cumulative[index - 1]) / span
    lat = points[index - 1][0] + fraction * (points[index][0] - points[index - 1][0])
    lon = points[index - 1][1] + fraction * (points[index][1] - points[index - 1][1])
    when = times[index - 1] + fraction * (times[index] - times[index - 1])
    return lat, lon, when


def bearing_deg(start: tuple[float, float], end: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(start[0]), math.radians(start[1])
    lat2, lon2 = math.radians(end[0]), math.radians(end[1])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def offset_point(lat: float, lon: float, bearing: float, miles: float) -> tuple[float, float]:
    angular = miles / EARTH_MILES
    theta = math.radians(bearing)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular) + math.cos(lat1) * math.sin(angular) * math.cos(theta)
    )
    lon2 = lon1 + math.atan2(
        math.sin(theta) * math.sin(angular) * math.cos(lat1),
        math.cos(angular) - math.sin(lat1) * math.sin(lat2),
    )
    degrees_lon = (math.degrees(lon2) + 540) % 360 - 180
    return math.degrees(lat2), degrees_lon


def _next_delta(encoded: str, index: int) -> tuple[int, int]:
    shift = 0
    result = 0
    while True:
        chunk = ord(encoded[index]) - 63
        index += 1
        result |= (chunk & 0x1F) << shift
        shift += 5
        if chunk < 0x20:
            break
    delta = ~(result >> 1) if result & 1 else result >> 1
    return delta, index


def _encode_value(value: int) -> str:
    signed = ~(value << 1) if value < 0 else value << 1
    chunks: list[str] = []
    while signed >= 0x20:
        chunks.append(chr((0x20 | (signed & 0x1F)) + 63))
        signed >>= 5
    chunks.append(chr(signed + 63))
    return "".join(chunks)


def _clamp_index(value: object, count: int) -> int:
    try:
        index = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(count - 1, index))


def _fill_time_gaps(times: list[float | None], cumulative: list[float]) -> None:
    known = [index for index, value in enumerate(times) if value is not None]
    if not known:
        return
    for index in range(known[0]):
        times[index] = times[known[0]]
    for left, right in zip(known, known[1:]):
        span = cumulative[right] - cumulative[left]
        start = float(times[left])
        end = float(times[right])
        for index in range(left + 1, right):
            fraction = 0.0 if span <= 1e-9 else (cumulative[index] - cumulative[left]) / span
            times[index] = start + fraction * (end - start)
    for index in range(known[-1] + 1, len(times)):
        times[index] = times[known[-1]]
