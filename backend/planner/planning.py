"""Turn a trip request into scored routes and a 48-hour corridor."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from planner.geocode import GeocodeError, search
from planner.geometry import cumulative_miles
from planner.risk import LEVEL_RANK, checkpoint_risk, worse
from planner.routing import RoutingError, fetch_routes, places_are_distinct
from planner.sampling import corridor_points, sample_checkpoints, slice_polyline
from planner.scoring import explain, rank_routes, summarize
from planner.weather import (
    Hourly,
    WeatherError,
    fetch_forecasts,
    forecast_for,
    forecast_hours,
    limit_locations,
    weather_key,
)

SAMPLE_MILES = (10, 25, 50)


class PlanError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def plan_trip(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise PlanError("The trip request could not be read.")
    origin = _place(payload.get("origin"), "origin")
    destination = _place(payload.get("destination"), "destination")
    origin_xy = (origin["latitude"], origin["longitude"])
    destination_xy = (destination["latitude"], destination["longitude"])
    if not places_are_distinct(origin_xy, destination_xy):
        raise PlanError("Origin and destination need to be at least a mile apart.")

    departure = _departure(payload.get("departure"))
    load_lb = _load(payload.get("load_lb"))
    interval = _interval(payload.get("sample_miles"))

    try:
        raw_routes, warnings = fetch_routes(origin_xy, destination_xy, load_lb)
    except RoutingError as exc:
        raise PlanError(str(exc), status=exc.status) from exc

    prepared = []
    for route in raw_routes:
        samples = sample_checkpoints(route["points"], route["times"], interval)
        prepared.append({**route, "samples": samples})

    hours = forecast_hours()
    latest = departure
    for route in prepared:
        latest = max(latest, departure + timedelta(seconds=route["duration_sec"]))
    horizon_hours = max(48, (latest - hours[0]).total_seconds() / 3600)
    forecast_days = min(16, max(3, int(horizon_hours / 24) + 2))
    keys = limit_locations(_weather_points(prepared), forecast_days)

    try:
        forecasts = fetch_forecasts(keys, forecast_days)
    except WeatherError as exc:
        raise PlanError(str(exc), status=exc.status) from exc

    outside_forecast = False
    built = []
    for route in prepared:
        checkpoints, missed = _checkpoints(route["samples"], forecasts, departure, load_lb)
        outside_forecast = outside_forecast or missed
        cumulative = cumulative_miles(route["points"])
        segments = []
        for start, end in zip(checkpoints, checkpoints[1:]):
            segments.append(
                {
                    "level": worse(start["level"], end["level"]),
                    "miles": round(end["mile"] - start["mile"], 2),
                    "geometry": slice_polyline(
                        route["points"],
                        cumulative,
                        route["times"],
                        start["mile"],
                        end["mile"],
                    ),
                }
            )
        built.append(
            {
                "id": route["id"],
                "label": route["label"],
                "subtitle": route["subtitle"],
                "truck_restricted": route["truck_restricted"],
                "recommended": False,
                "distance_mi": round(route["distance_mi"], 1),
                "duration_min": round(route["duration_sec"] / 60, 1),
                "summary": summarize(checkpoints),
                "checkpoints": checkpoints,
                "segments": segments,
            }
        )

    scored = [
        checkpoint
        for route in built
        for checkpoint in route["checkpoints"]
    ]
    if scored and all(checkpoint["level"] == "unknown" for checkpoint in scored):
        warnings.append("The departure is outside the available forecast, so weather risk could not be scored.")
    elif outside_forecast:
        warnings.append(
            "Some checkpoints are outside the available forecast and were left out of the mile totals."
        )

    ranked = rank_routes(built)
    heatmap = _heatmap(forecasts, keys, hours, load_lb)
    return {
        "origin": origin,
        "destination": destination,
        "departure": departure.isoformat(),
        "load_lb": load_lb,
        "sample_miles": interval,
        "routes": ranked,
        "heatmap": heatmap,
        "recommendation": {
            "route_id": ranked[0]["id"],
            "explanation": explain(ranked),
        },
        "warnings": warnings,
    }


def _checkpoints(
    samples: list[dict],
    forecasts: dict[tuple[float, float], Hourly],
    departure: datetime,
    load_lb: float,
) -> tuple[list[dict], bool]:
    checkpoints = []
    missed = False
    for sample in samples:
        eta = departure + timedelta(seconds=sample["offset_sec"])
        hourly = forecast_for(forecasts, sample["lat"], sample["lon"])
        reading = hourly.at(eta) if hourly else None
        base = {
            "mile": round(sample["mile"], 2),
            "lat": round(sample["lat"], 5),
            "lon": round(sample["lon"], 5),
            "eta": eta.isoformat(),
        }
        if reading is None:
            missed = True
            checkpoints.append(
                {
                    **base,
                    "wind_mph": None,
                    "rain_in_hr": None,
                    "snow_in_hr": None,
                    "wind_level": "unknown",
                    "rain_level": "unknown",
                    "snow_level": "unknown",
                    "level": "unknown",
                    "reasons": ["No forecast is available for this arrival time"],
                }
            )
            continue
        wind, rain, snow = reading
        risk = checkpoint_risk(wind, rain, snow, load_lb)
        checkpoints.append(
            {
                **base,
                "wind_mph": round(wind, 1),
                "rain_in_hr": round(rain, 3),
                "snow_in_hr": round(snow, 3),
                **risk,
            }
        )
    return checkpoints, missed


def _heatmap(
    forecasts: dict[tuple[float, float], Hourly],
    keys: list[tuple[float, float]],
    hours: list[datetime],
    load_lb: float,
) -> dict:
    points = []
    for key in keys:
        hourly = forecast_for(forecasts, key[0], key[1])
        levels = []
        for hour in hours:
            reading = hourly.at(hour) if hourly else None
            if reading is None:
                levels.append(0)
                continue
            wind, rain, snow = reading
            level = checkpoint_risk(wind, rain, snow, load_lb)["level"]
            levels.append(LEVEL_RANK[level])
        points.append({"lat": key[0], "lon": key[1], "levels": levels})
    return {
        "hours": [hour.isoformat() for hour in hours],
        "points": points,
    }


def _weather_points(routes: list[dict]) -> list[tuple[float, float]]:
    keys: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for route in routes:
        for sample in route["samples"]:
            key = weather_key(sample["lat"], sample["lon"])
            if key not in seen:
                seen.add(key)
                keys.append(key)
    for lat, lon in corridor_points([route["points"] for route in routes]):
        key = (lat, lon)
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def _place(value: object, field: str) -> dict:
    if isinstance(value, str):
        query = value.strip()
        if not query:
            raise PlanError(f"Enter an {field}.")
        try:
            hits = search(query, count=1)
        except GeocodeError as exc:
            raise PlanError(str(exc), status=exc.status) from exc
        if not hits:
            raise PlanError(f"No place found for {field}: {query}.")
        return hits[0]
    if isinstance(value, dict):
        try:
            lat = float(value["latitude"])
            lon = float(value["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PlanError(f"Choose a suggested place for the {field}.") from exc
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise PlanError(f"The {field} coordinates are out of range.")
        label = str(value.get("label") or f"{lat:.3f}, {lon:.3f}")
        return {"label": label, "latitude": lat, "longitude": lon}
    raise PlanError(f"Enter an {field}.")


def _departure(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PlanError("Choose a departure date and time.")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PlanError("Departure time could not be read.") from exc
    if parsed.tzinfo is None:
        raise PlanError("Departure time must include a time zone.")
    return parsed.astimezone(timezone.utc)


def _load(value: object) -> float:
    try:
        load = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise PlanError("Enter a load weight in pounds.") from exc
    if load < 0 or load > 200_000:
        raise PlanError("Load weight must be between 0 and 200,000 lb.")
    return load


def _interval(value: object) -> int:
    try:
        interval = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise PlanError("Choose a sample interval of 10, 25, or 50 miles.") from exc
    if interval not in SAMPLE_MILES:
        raise PlanError("Choose a sample interval of 10, 25, or 50 miles.")
    return interval
