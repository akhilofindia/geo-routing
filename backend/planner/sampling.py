"""Checkpoint spacing and the corridor sample used by the heatmap."""

from __future__ import annotations

from planner.geometry import (
    bearing_deg,
    cumulative_miles,
    interpolate,
    offset_point,
)


def sample_checkpoints(
    points: list[tuple[float, float]],
    times: list[float],
    interval_miles: float,
) -> list[dict]:
    """Origin, every interval, and the destination.

    Miles and ETA are interpolated along the shape. A trip shorter than the
    interval still returns both ends.
    """
    if not points:
        return []
    cumulative = cumulative_miles(points)
    total = cumulative[-1]
    targets = [0.0]
    if total > 0.05:
        mile = float(interval_miles)
        while mile < total - 0.05:
            targets.append(mile)
            mile += float(interval_miles)
        if total - targets[-1] > 0.05:
            targets.append(total)

    samples = []
    for mile in targets:
        lat, lon, offset_sec = interpolate(points, cumulative, times, mile)
        samples.append(
            {
                "mile": mile,
                "lat": lat,
                "lon": lon,
                "offset_sec": offset_sec,
            }
        )
    return samples


def slice_polyline(
    points: list[tuple[float, float]],
    cumulative: list[float],
    times: list[float],
    start_mile: float,
    end_mile: float,
) -> list[list[float]]:
    """Coordinates covering one checkpoint-to-checkpoint segment."""
    start = interpolate(points, cumulative, times, start_mile)
    end = interpolate(points, cumulative, times, end_mile)
    coords = [[round(start[0], 5), round(start[1], 5)]]
    for point, mile in zip(points, cumulative):
        if start_mile + 1e-6 < mile < end_mile - 1e-6:
            coords.append([round(point[0], 5), round(point[1], 5)])
    last = [round(end[0], 5), round(end[1], 5)]
    if coords[-1] != last:
        coords.append(last)
    return coords


def corridor_points(
    routes: list[list[tuple[float, float]]],
    step_miles: float = 20,
    offset_miles: float = 12,
) -> list[tuple[float, float]]:
    """Points along each route, plus a left and right offset, on a 0.05° grid."""
    seen: set[tuple[float, float]] = set()
    chosen: list[tuple[float, float]] = []
    for points in routes:
        if len(points) < 2:
            continue
        cumulative = cumulative_miles(points)
        total = cumulative[-1]
        times = [0.0] * len(points)
        targets = [0.0]
        mile = step_miles
        while mile < total - 0.05:
            targets.append(mile)
            mile += step_miles
        if total - targets[-1] > 0.05:
            targets.append(total)
        for mile in targets:
            lat, lon, _offset = interpolate(points, cumulative, times, mile)
            before, _b, _t = interpolate(points, cumulative, times, max(0.0, mile - 1))
            after, _a, _u = interpolate(points, cumulative, times, min(total, mile + 1))
            heading = bearing_deg((before, _b), (after, _a))
            candidates = [
                (lat, lon),
                offset_point(lat, lon, (heading + 90) % 360, offset_miles),
                offset_point(lat, lon, (heading - 90) % 360, offset_miles),
            ]
            for candidate in candidates:
                _remember(chosen, seen, candidate)
    return chosen


def _remember(
    chosen: list[tuple[float, float]],
    seen: set[tuple[float, float]],
    point: tuple[float, float],
) -> None:
    key = (round(round(point[0] / 0.05) * 0.05, 2), round(round(point[1] / 0.05) * 0.05, 2))
    if key in seen:
        return
    seen.add(key)
    chosen.append(key)
