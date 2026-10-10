"""Open-Meteo hourly forecasts, keyed by rounded coordinates."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import requests

from planner.geometry import haversine_miles

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "truck-route-planner/1.0"
CHUNK_SIZE = 25
# One location counts as one lookup. A cross-country trip must stay well under
# the free service's 600 lookups per minute.
LOOKUP_BUDGET = 80


class WeatherError(Exception):
    def __init__(self, message: str, *, status: int = 502):
        super().__init__(message)
        self.status = status


class Hourly:
    def __init__(self, times: list[datetime], wind: list[float], rain: list[float], snow: list[float]):
        self.times = times
        self.wind = wind
        self.rain = rain
        self.snow = snow

    def at(self, moment: datetime) -> tuple[float, float, float] | None:
        """Wind mph, rain in/hr, and snow in/hr for the hour that contains moment."""
        if not self.times:
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        hour = moment.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        if hour < self.times[0] or hour > self.times[-1]:
            return None
        index = int((hour - self.times[0]).total_seconds() // 3600)
        if index < 0 or index >= len(self.times) or index >= len(self.wind) or self.times[index] != hour:
            return None
        wind = self.wind[index]
        if wind is None:
            return None
        rain = self.rain[index] if index < len(self.rain) and self.rain[index] is not None else 0.0
        snow = self.snow[index] if index < len(self.snow) and self.snow[index] is not None else 0.0
        return float(wind), float(rain), float(snow)


def weather_key(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, 2), round(lon, 2))


def limit_locations(points: list[tuple[float, float]], forecast_days: int) -> list[tuple[float, float]]:
    """Snap a long corridor onto a grid small enough for one forecast lookup."""
    unique = list(dict.fromkeys(points))
    budget = max(24, int(LOOKUP_BUDGET / max(1.0, forecast_days / 7)))
    if len(unique) <= budget:
        return unique
    chosen = unique
    for cell in (0.2, 0.3, 0.45, 0.6, 0.8, 1.1, 1.6):
        seen: set[tuple[float, float]] = set()
        chosen = []
        for lat, lon in unique:
            key = (round(round(lat / cell) * cell, 2), round(round(lon / cell) * cell, 2))
            if key in seen:
                continue
            seen.add(key)
            chosen.append(key)
        if len(chosen) <= budget:
            return chosen
    return chosen[:budget]


def forecast_for(
    forecasts: dict[tuple[float, float], Hourly],
    lat: float,
    lon: float,
    max_miles: float = 90,
) -> Hourly | None:
    """Exact grid hit, or the closest fetched forecast along the corridor."""
    exact = forecasts.get(weather_key(lat, lon))
    if exact is not None:
        return exact
    best: Hourly | None = None
    best_miles = max_miles
    for (point_lat, point_lon), hourly in forecasts.items():
        miles = haversine_miles((lat, lon), (point_lat, point_lon))
        if miles < best_miles:
            best = hourly
            best_miles = miles
    return best


def fetch_forecasts(points: list[tuple[float, float]], forecast_days: int) -> dict[tuple[float, float], Hourly]:
    unique = list(dict.fromkeys(points))
    if not unique:
        return {}
    days = max(1, min(16, int(forecast_days)))
    merged: dict[tuple[float, float], Hourly] = {}
    for start in range(0, len(unique), CHUNK_SIZE):
        merged.update(_fetch_chunk(unique[start : start + CHUNK_SIZE], days))
    return merged


def forecast_hours(now: datetime | None = None) -> list[datetime]:
    """Forty-nine timestamps: the current hour and the next 48 hours."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    start = moment.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [start + timedelta(hours=offset) for offset in range(49)]


def _fetch_chunk(points: list[tuple[float, float]], forecast_days: int) -> dict[tuple[float, float], Hourly]:
    params = {
        "latitude": ",".join(f"{lat:.4f}" for lat, _lon in points),
        "longitude": ",".join(f"{lon:.4f}" for _lat, lon in points),
        "hourly": "wind_speed_10m,rain,showers,snowfall",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "UTC",
        "forecast_days": forecast_days,
    }
    payload = None
    response = None
    for attempt in range(3):
        try:
            response = requests.get(
                FORECAST_URL,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
        except requests.Timeout as exc:
            raise WeatherError("The weather service timed out. Try again in a moment.", status=504) from exc
        except requests.RequestException as exc:
            raise WeatherError("The weather service did not respond. Try again in a moment.", status=502) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            if response.status_code >= 500:
                raise WeatherError("The weather service is unavailable. Try again in a moment.", status=502) from exc
            raise WeatherError("The weather service returned an unreadable response.", status=502) from exc
        reason = str(payload.get("reason") or "") if isinstance(payload, dict) else ""
        limited = response.status_code == 429 or "limit" in reason.lower()
        if limited and "minute" in reason.lower() and attempt < 2:
            time.sleep(12)
            continue
        break

    if response is None or payload is None:
        raise WeatherError("The weather service did not respond. Try again in a moment.", status=502)
    if response.status_code == 429 or (isinstance(payload, dict) and payload.get("error") and "limit" in str(payload.get("reason") or "").lower()):
        raise WeatherError(describe_weather_reason(str(payload.get("reason") or "")), status=503)
    if isinstance(payload, dict) and payload.get("error"):
        raise WeatherError(describe_weather_reason(str(payload.get("reason") or "")), status=400)
    if response.status_code >= 500:
        raise WeatherError("The weather service is unavailable. Try again in a moment.", status=502)
    if response.status_code >= 400:
        raise WeatherError("The weather service rejected the request.", status=400)
    items = payload if isinstance(payload, list) else [payload]
    if len(items) != len(points):
        raise WeatherError("The weather service returned an unexpected response.")

    parsed: dict[tuple[float, float], Hourly] = {}
    for point, item in zip(points, items):
        parsed[point] = _parse_hourly(item)
    return parsed


def describe_weather_reason(reason: str) -> str:
    text = reason.lower()
    if "daily" in text and "limit" in text:
        return "The weather service's daily lookup limit was reached. Try again tomorrow."
    if "hourly" in text and "limit" in text:
        return "The weather service's hourly lookup limit was reached. Try again in about an hour."
    if "minutely" in text and "limit" in text:
        return "The weather service allows a limited number of lookups per minute. Try again in a minute."
    if "limit" in text:
        return "The weather service's lookup limit was reached. Try again in a minute."
    if "latitude" in text or "longitude" in text or "invalid" in text:
        return "A route point is outside the area the weather service covers."
    if reason and len(reason) <= 180 and "<" not in reason:
        return f"The weather service rejected the request: {reason}"
    return "The weather service rejected the request."


def _parse_hourly(item: dict) -> Hourly:
    hourly = item.get("hourly") or {}
    stamps = hourly.get("time") or []
    times = [datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc) for stamp in stamps]
    wind = [_number(value) for value in hourly.get("wind_speed_10m") or []]
    rain_values = hourly.get("rain") or []
    shower_values = hourly.get("showers") or []
    rain = [_sum_pair(rain_values, shower_values, index) for index in range(len(times))]
    snow = [_number(value) or 0.0 for value in (hourly.get("snowfall") or [])]
    if len(snow) < len(times):
        snow.extend([0.0] * (len(times) - len(snow)))
    return Hourly(times, wind, rain, snow)


def _sum_pair(rain: list, showers: list, index: int) -> float:
    rain_value = _number(rain[index]) if index < len(rain) else 0.0
    shower_value = _number(showers[index]) if index < len(showers) else 0.0
    return (rain_value or 0.0) + (shower_value or 0.0)


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
