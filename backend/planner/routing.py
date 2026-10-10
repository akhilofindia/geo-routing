"""Truck routes from Valhalla, with an OSRM fallback when that service is down."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import requests

from planner.geometry import (
    bearing_deg,
    cumulative_miles,
    decode_polyline,
    haversine_miles,
    interpolate,
    offset_point,
    vertex_times,
)

VALHALLA_URL = "https://valhalla1.openstreetmap.de/route"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
USER_AGENT = "truck-route-planner/1.0"
METERS_PER_MILE = 1609.344
# Public Valhalla rejects a path longer than 1,500 km. Stay under that per request.
SECTION_MILES = 600


class RoutingError(Exception):
    def __init__(self, message: str, *, status: int = 502, code: str = "down"):
        super().__init__(message)
        self.status = status
        self.code = code


def fetch_routes(
    origin: tuple[float, float],
    destination: tuple[float, float],
    load_lb: float,
) -> tuple[list[dict], list[str]]:
    """Return up to three route geometries and any user-facing warnings."""
    warnings: list[str] = []
    truck_restricted = True
    try:
        routes = _valhalla_set(origin, destination, load_lb)
    except RoutingError as exc:
        if exc.code == "distance":
            try:
                routes = _segmented_truck_routes(origin, destination, load_lb)
            except RoutingError as fallback:
                raise prefer_routing_error(exc, fallback) from fallback
            warnings.append(
                "This trip is longer than the truck router allows in one request, so it was planned in sections."
            )
        else:
            try:
                routes = _osrm_routes(origin, destination)
            except RoutingError as fallback:
                raise prefer_routing_error(exc, fallback) from fallback
            warnings.append(_driving_warning(exc))
            truck_restricted = False

    unique: list[dict] = []
    for route in routes:
        signature = _signature(route["points"])
        if any(_overlap(signature, existing["signature"]) >= 0.75 for existing in unique):
            continue
        route["signature"] = signature
        route.setdefault("truck_restricted", truck_restricted)
        unique.append(route)
        if len(unique) == 3:
            break

    if not unique:
        raise RoutingError("No drivable road connects those places.", status=400, code="no_route")
    if len(unique) < 3:
        _add_offset_routes(origin, destination, load_lb, unique)
    if any(not route.get("truck_restricted", True) for route in unique):
        note = "Part of this trip could not be truck-routed. Those stretches use a general driving route."
        if note not in warnings:
            warnings.append(note)
    if len(unique) < 3:
        warnings.append(f"Only {len(unique)} distinct route{'s' if len(unique) != 1 else ''} were found.")

    for index, route in enumerate(unique, start=1):
        route["id"] = f"route-{index}"
        route["label"] = f"Route {index}"
        route.pop("signature", None)
    return unique, warnings


def _valhalla_set(
    origin: tuple[float, float],
    destination: tuple[float, float],
    load_lb: float,
) -> list[dict]:
    primary = _valhalla(origin, destination, load_lb, alternates=2, use_tolls=1, use_highways=1)
    routes = [
        _describe(trip, "Fastest truck route" if index == 0 else "Alternate truck route")
        for index, trip in enumerate(primary)
    ]
    if _count_unique(routes) < 3:
        for trip in _extra_routes(origin, destination, load_lb, use_tolls=0, use_highways=1):
            routes.append(_describe(trip, "Avoids tolls"))
    if _count_unique(routes) < 3:
        for trip in _extra_routes(origin, destination, load_lb, use_tolls=1, use_highways=0.15):
            routes.append(_describe(trip, "Fewer highways"))
    if _count_unique(routes) < 3 and routes:
        for trip in _via_routes(origin, destination, load_lb, routes[0]["points"]):
            routes.append(_describe(trip, "Offset alternate"))
    return routes


def _extra_routes(
    origin: tuple[float, float],
    destination: tuple[float, float],
    load_lb: float,
    use_tolls: float,
    use_highways: float,
) -> list[dict]:
    try:
        return _valhalla(
            origin,
            destination,
            load_lb,
            alternates=0,
            use_tolls=use_tolls,
            use_highways=use_highways,
        )
    except RoutingError:
        return []


def _count_unique(routes: list[dict]) -> int:
    signatures: list[set[tuple[float, float]]] = []
    for route in routes:
        signature = _signature(route["points"])
        if any(_overlap(signature, existing) >= 0.75 for existing in signatures):
            continue
        signatures.append(signature)
    return len(signatures)


def _via_routes(
    origin: tuple[float, float],
    destination: tuple[float, float],
    load_lb: float,
    points: list[tuple[float, float]],
) -> list[dict]:
    via = _offset_midpoint(points)
    if via is None:
        return []
    try:
        return _valhalla(
            origin,
            destination,
            load_lb,
            alternates=0,
            use_tolls=1,
            use_highways=1,
            via=via,
        )
    except RoutingError:
        return []


def _offset_midpoint(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    if len(points) < 2:
        return None
    cumulative = cumulative_miles(points)
    total = cumulative[-1]
    if total < 40:
        return None
    mile = total / 2
    times = [0.0] * len(points)
    lat, lon, _when = interpolate(points, cumulative, times, mile)
    before_lat, before_lon, _before = interpolate(points, cumulative, times, max(0.0, mile - 5))
    after_lat, after_lon, _after = interpolate(points, cumulative, times, min(total, mile + 5))
    heading = bearing_deg((before_lat, before_lon), (after_lat, after_lon))
    distance = min(45.0, max(15.0, total * 0.12))
    return offset_point(lat, lon, (heading + 90) % 360, distance)


def _valhalla(
    origin: tuple[float, float],
    destination: tuple[float, float],
    load_lb: float,
    alternates: int,
    use_tolls: float,
    use_highways: float,
    via: tuple[float, float] | None = None,
) -> list[dict]:
    locations = [{"lat": origin[0], "lon": origin[1]}]
    if via is not None:
        locations.append({"lat": via[0], "lon": via[1], "type": "via"})
        alternates = 0
    locations.append({"lat": destination[0], "lon": destination[1]})
    body = {
        "locations": locations,
        "costing": "truck",
        "units": "miles",
        "alternates": alternates,
        "costing_options": {
            "truck": {
                "weight": round(load_lb / 2204.6226218, 2),
                "use_tolls": use_tolls,
                "use_highways": use_highways,
            }
        },
    }
    payload = _post_json(VALHALLA_URL, body)
    trip = payload.get("trip")
    if not trip:
        message = payload.get("error") if isinstance(payload, dict) else None
        code = payload.get("error_code") if isinstance(payload, dict) else None
        raise describe_valhalla_failure(str(message or ""), code if isinstance(code, int) else None, 400)
    trips = [trip]
    for alternate in payload.get("alternates") or []:
        if alternate.get("trip"):
            trips.append(alternate["trip"])
    return trips


def _describe(trip: dict, subtitle: str) -> dict:
    legs = trip.get("legs") or []
    points: list[tuple[float, float]] = []
    maneuvers: list[dict] = []
    for leg in legs:
        shape = leg.get("shape")
        if not shape:
            continue
        leg_points = decode_polyline(shape, precision=6)
        base = len(points) - 1 if points else 0
        if points and leg_points:
            leg_points = leg_points[1:]
        points.extend(leg_points)
        for maneuver in leg.get("maneuvers") or []:
            begin = int(maneuver.get("begin_shape_index") or 0)
            end = int(maneuver.get("end_shape_index") or begin)
            maneuvers.append(
                {
                    "begin_shape_index": base + begin,
                    "end_shape_index": base + end,
                    "time": maneuver.get("time") or 0,
                }
            )
    if len(points) < 2:
        raise RoutingError("The truck router returned a route without a path.", status=502, code="unreadable")
    summary = trip.get("summary") or {}
    duration = float(summary.get("time") or 0)
    distance = float(summary.get("length") or 0)
    if duration <= 0:
        duration = sum(float((leg.get("summary") or {}).get("time") or 0) for leg in legs)
    if distance <= 0:
        distance = sum(float((leg.get("summary") or {}).get("length") or 0) for leg in legs)
    times = vertex_times(points, maneuvers, duration)
    return {
        "subtitle": subtitle,
        "points": points,
        "times": times,
        "distance_mi": distance,
        "duration_sec": duration,
    }


def section_targets(total_miles: float, step_miles: float = SECTION_MILES) -> list[float]:
    """Mile marks that keep each routing request under the public distance cap."""
    if total_miles <= 0:
        return [0.0]
    targets = [0.0]
    mile = step_miles
    while mile < total_miles - 40:
        targets.append(mile)
        mile += step_miles
    if total_miles - targets[-1] > 0.05:
        targets.append(total_miles)
    return targets


def describe_valhalla_failure(message: str, error_code: int | None, status_code: int) -> RoutingError:
    """Turn a Valhalla error into a specific message."""
    text = message.lower()
    if "max distance" in text or error_code == 154:
        return RoutingError(
            "That trip is longer than the truck router accepts in one request.",
            status=400,
            code="distance",
        )
    if "no suitable edges" in text or "no segment" in text or error_code in {124, 171}:
        return RoutingError(
            "One of those places is not close enough to a drivable road.",
            status=400,
            code="off_road",
        )
    if "coverage" in text or "outside the" in text:
        return RoutingError(
            "Those places are outside the mapped road network.",
            status=400,
            code="outside",
        )
    if any(phrase in text for phrase in ("no path", "no route", "unconnected", "impossible")) or error_code in {170, 442}:
        return RoutingError("No drivable road connects those places.", status=400, code="no_route")
    if status_code == 429:
        return RoutingError("The truck router is busy. Try again in a moment.", status=503, code="busy")
    if status_code >= 500:
        return RoutingError("The truck router is unavailable. Try again in a moment.", status=502, code="down")
    return RoutingError("The truck router could not plan that trip.", status=400, code="rejected")


def describe_osrm_failure(code: str, status_code: int) -> RoutingError:
    """Turn an OSRM error into a specific message."""
    if code == "NoSegment":
        return RoutingError(
            "One of those places is not close enough to a drivable road.",
            status=400,
            code="off_road",
        )
    if code in {"NoRoute", "Impossible"} or (status_code == 400 and not code):
        return RoutingError("No drivable road connects those places.", status=400, code="no_route")
    if code == "TooBig":
        return RoutingError("That trip is too long for the routing service.", status=400, code="distance")
    if status_code == 429 or code == "TooManyRequests":
        return RoutingError("The routing service is busy. Try again in a moment.", status=503, code="busy")
    if status_code >= 500:
        return RoutingError("The routing service is unavailable. Try again in a moment.", status=502, code="down")
    return RoutingError("The routing service rejected the request. Try again in a moment.", status=502, code="down")


def prefer_routing_error(primary: RoutingError, fallback: RoutingError) -> RoutingError:
    """Keep a geographic answer when the backup router fails for a different reason."""
    geographic = {"no_route", "off_road", "outside"}
    if fallback.code in geographic:
        return fallback
    if primary.code in geographic:
        lead = {
            "no_route": "No truck route connects those places",
            "off_road": "One of those places is not close enough to a road",
            "outside": "Those places are outside the mapped road network",
        }[primary.code]
        if fallback.code == "busy":
            tail = "the backup router is busy. Try again in a moment."
        elif fallback.code == "timeout":
            tail = "the backup router timed out. Try again in a moment."
        else:
            tail = "the backup router did not respond. Try again in a moment."
        return RoutingError(f"{lead}, and {tail}", status=fallback.status, code=fallback.code)
    if primary.code == "distance" or fallback.code == "distance":
        return RoutingError("That trip is too long to route.", status=400, code="distance")
    if fallback.code == "busy" and primary.code == "busy":
        return RoutingError("The routing service is busy. Try again in a moment.", status=503, code="busy")
    if "timeout" in {primary.code, fallback.code} and "down" not in {primary.code, fallback.code}:
        return RoutingError("The routing service timed out. Try again in a moment.", status=504, code="timeout")
    return RoutingError("The routing service did not respond. Try again in a moment.", status=502, code="down")


def _driving_warning(exc: RoutingError) -> str:
    if exc.code == "no_route":
        reason = "No truck route was found."
    elif exc.code == "off_road":
        reason = "The truck router could not match a place to a road."
    elif exc.code == "outside":
        reason = "The truck router does not cover those places."
    elif exc.code == "timeout":
        reason = "The truck router timed out."
    elif exc.code == "busy":
        reason = "The truck router is busy."
    else:
        reason = "The truck router did not respond."
    return f"{reason} Showing a general driving route instead. It does not apply truck road restrictions."


def _segmented_truck_routes(
    origin: tuple[float, float],
    destination: tuple[float, float],
    load_lb: float,
) -> list[dict]:
    corridors = _osrm_routes(origin, destination)
    routes = []
    for index, corridor in enumerate(corridors):
        subtitle = "Fastest truck route" if index == 0 else "Alternate truck route"
        try:
            route = _truck_along(corridor["points"], load_lb, subtitle)
        except RoutingError:
            route = corridor
            route["subtitle"] = "Driving route, not truck-restricted"
            route["truck_restricted"] = False
        else:
            route["truck_restricted"] = True
        routes.append(route)
    return routes


def _truck_along(points: list[tuple[float, float]], load_lb: float, subtitle: str) -> dict:
    cumulative = cumulative_miles(points)
    total = cumulative[-1]
    targets = section_targets(total)
    if len(targets) < 2:
        raise RoutingError("No drivable road connects those places.", status=400, code="no_route")
    clock = [0.0] * len(points)
    anchors = []
    for mile in targets:
        lat, lon, _when = interpolate(points, cumulative, clock, mile)
        if not anchors or haversine_miles(anchors[-1], (lat, lon)) >= 1:
            anchors.append((lat, lon))
    if len(anchors) < 2:
        raise RoutingError("No drivable road connects those places.", status=400, code="no_route")
    pairs = list(zip(anchors, anchors[1:]))
    workers = min(4, len(pairs))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        sections = list(pool.map(lambda pair: _one_truck_leg(pair[0], pair[1], load_lb), pairs))
    return _stitch(sections, subtitle)


def _one_truck_leg(
    start: tuple[float, float],
    end: tuple[float, float],
    load_lb: float,
) -> dict:
    trips = _valhalla(start, end, load_lb, alternates=0, use_tolls=1, use_highways=1)
    return _describe(trips[0], "")


def _stitch(sections: list[dict], subtitle: str) -> dict:
    points: list[tuple[float, float]] = []
    times: list[float] = []
    distance = 0.0
    duration = 0.0
    for section in sections:
        part_points = section["points"]
        part_times = section["times"]
        if points and part_points:
            part_points = part_points[1:]
            part_times = part_times[1:]
        points.extend(part_points)
        times.extend(duration + value for value in part_times)
        distance += float(section["distance_mi"])
        duration += float(section["duration_sec"])
    if len(points) < 2 or len(times) != len(points):
        raise RoutingError("The truck router returned a route without a path.", status=502, code="unreadable")
    return {
        "subtitle": subtitle,
        "points": points,
        "times": times,
        "distance_mi": distance,
        "duration_sec": duration,
    }


def via_candidates(routes: list[dict]) -> list[tuple[float, float]]:
    """Points well off the routes already found, so a third corridor can be forced."""
    if not routes or len(routes[0].get("points") or []) < 2:
        return []
    primary = routes[0]["points"]
    cumulative = cumulative_miles(primary)
    total = cumulative[-1]
    if total < 80:
        return []
    occupied: list[tuple[float, float]] = []
    for route in routes:
        points = route.get("points") or []
        if len(points) < 2:
            continue
        along = cumulative_miles(points)
        step = max(20.0, along[-1] / 30)
        mile = 0.0
        clock = [0.0] * len(points)
        while mile <= along[-1]:
            lat, lon, _when = interpolate(points, along, clock, mile)
            occupied.append((lat, lon))
            mile += step
    if not occupied:
        return []
    base = min(160.0, max(70.0, total * 0.09))
    clock = [0.0] * len(primary)
    ranked: list[tuple[float, tuple[float, float]]] = []
    for fraction in (0.35, 0.5, 0.65):
        mile = total * fraction
        lat, lon, _when = interpolate(primary, cumulative, clock, mile)
        before_lat, before_lon, _before = interpolate(primary, cumulative, clock, max(0.0, mile - 8))
        after_lat, after_lon, _after = interpolate(primary, cumulative, clock, min(total, mile + 8))
        heading = bearing_deg((before_lat, before_lon), (after_lat, after_lon))
        for side in (90, -90):
            for distance in (base, min(220.0, base * 1.6)):
                point = offset_point(lat, lon, (heading + side) % 360, distance)
                if haversine_miles(point, primary[0]) < 100 or haversine_miles(point, primary[-1]) < 100:
                    continue
                gap = min(haversine_miles(point, place) for place in occupied)
                if gap >= 45:
                    ranked.append((gap, point))
    ranked.sort(key=lambda item: item[0], reverse=True)
    chosen: list[tuple[float, float]] = []
    for _gap, point in ranked:
        if all(haversine_miles(point, other) > 40 for other in chosen):
            chosen.append(point)
        if len(chosen) == 3:
            break
    return chosen


def _add_offset_routes(
    origin: tuple[float, float],
    destination: tuple[float, float],
    load_lb: float,
    routes: list[dict],
) -> None:
    """Add a corridor through a point the routes found so far do not use."""
    for via in via_candidates(routes):
        if _count_unique(routes) >= 3:
            return
        try:
            corridors = _osrm_routes(origin, destination, via=via)
        except RoutingError:
            continue
        corridor = corridors[0]
        try:
            route = _truck_along(corridor["points"], load_lb, "Offset alternate")
            route["truck_restricted"] = True
        except RoutingError:
            route = corridor
            route["subtitle"] = "Offset alternate, not truck-restricted"
            route["truck_restricted"] = False
        if _count_unique(routes + [route]) <= _count_unique(routes):
            continue
        route["signature"] = _signature(route["points"])
        routes.append(route)


def _osrm_routes(
    origin: tuple[float, float],
    destination: tuple[float, float],
    via: tuple[float, float] | None = None,
) -> list[dict]:
    stops = [origin]
    if via is not None:
        stops.append(via)
    stops.append(destination)
    coord_path = ";".join(f"{lon},{lat}" for lat, lon in stops)
    url = f"{OSRM_URL}/{coord_path}"
    try:
        response = requests.get(
            url,
            params={
                "alternatives": "false" if via is not None else "true",
                "overview": "full",
                "geometries": "geojson",
                "annotations": "duration,distance",
                "steps": "false",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=25,
        )
        payload = response.json()
    except requests.Timeout as exc:
        raise RoutingError(
            "The routing service timed out. Try again in a moment.",
            status=504,
            code="timeout",
        ) from exc
    except requests.RequestException as exc:
        raise RoutingError(
            "The routing service did not respond. Try again in a moment.",
            status=502,
            code="down",
        ) from exc
    except ValueError as exc:
        raise RoutingError(
            "The routing service returned an unreadable response.",
            status=502,
            code="unreadable",
        ) from exc
    if not isinstance(payload, dict) or payload.get("code") != "Ok":
        osrm_code = payload.get("code") if isinstance(payload, dict) else ""
        raise describe_osrm_failure(str(osrm_code or ""), response.status_code)

    routes = []
    for route in (payload.get("routes") or [])[:3]:
        geometry = (route.get("geometry") or {}).get("coordinates") or []
        points = [(pair[1], pair[0]) for pair in geometry]
        if len(points) < 2:
            continue
        duration = float(route.get("duration") or 0)
        times = _osrm_times(route, len(points), duration)
        routes.append(
            {
                "subtitle": "Driving route, not truck-restricted",
                "points": points,
                "times": times,
                "distance_mi": float(route.get("distance") or 0) / METERS_PER_MILE,
                "duration_sec": duration,
            }
        )
    if not routes:
        raise RoutingError("No drivable road connects those places.", status=400, code="no_route")
    return routes


def _osrm_times(route: dict, count: int, duration: float) -> list[float]:
    legs = route.get("legs") or []
    durations: list[float] = []
    for leg in legs:
        annotation = leg.get("annotation") or {}
        durations.extend(float(value) for value in annotation.get("duration") or [])
    if len(durations) == count - 1:
        times = [0.0]
        for value in durations:
            times.append(times[-1] + value)
        return times
    return [duration * index / (count - 1) for index in range(count)]


def _post_json(url: str, body: dict) -> dict:
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            response = requests.post(
                url,
                json=body,
                headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
                timeout=25,
            )
        except requests.Timeout as exc:
            last_error = RoutingError(
                "The truck router timed out. Try again in a moment.",
                status=504,
                code="timeout",
            )
            last_error.__cause__ = exc
            continue
        except requests.RequestException as exc:
            raise RoutingError(
                "The truck router did not respond. Try again in a moment.",
                status=502,
                code="down",
            ) from exc
        if response.status_code == 429:
            raise RoutingError("The truck router is busy. Try again in a moment.", status=503, code="busy")
        if response.status_code >= 500:
            last_error = RoutingError(
                "The truck router is unavailable. Try again in a moment.",
                status=502,
                code="down",
            )
            continue
        try:
            payload = response.json()
        except ValueError as exc:
            raise RoutingError(
                "The truck router returned an unreadable response.",
                status=502,
                code="unreadable",
            ) from exc
        if response.status_code >= 400:
            message = payload.get("error") if isinstance(payload, dict) else ""
            error_code = payload.get("error_code") if isinstance(payload, dict) else None
            raise describe_valhalla_failure(
                str(message or ""),
                error_code if isinstance(error_code, int) else None,
                response.status_code,
            )
        if not isinstance(payload, dict):
            raise RoutingError(
                "The truck router returned an unreadable response.",
                status=502,
                code="unreadable",
            )
        return payload
    if isinstance(last_error, RoutingError):
        raise last_error
    raise RoutingError("The truck router did not respond. Try again in a moment.", status=502, code="down")


def _signature(points: list[tuple[float, float]]) -> set[tuple[float, float]]:
    if len(points) <= 12:
        chosen = points
    else:
        step = (len(points) - 1) / 11
        chosen = [points[int(round(index * step))] for index in range(12)]
    return {(round(lat, 1), round(lon, 1)) for lat, lon in chosen}


def _overlap(left: set[tuple[float, float]], right: set[tuple[float, float]]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def places_are_distinct(origin: tuple[float, float], destination: tuple[float, float]) -> bool:
    return haversine_miles(origin, destination) >= 1
