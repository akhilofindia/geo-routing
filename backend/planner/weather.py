"""Hourly forecasts for the corridor.

US points come from the National Weather Service. The public Open-Meteo
forecast is only a fallback, because cloud hosts share its daily limit.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

from planner.geometry import haversine_miles

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
NWS_POINTS_URL = "https://api.weather.gov/points"
USER_AGENT = "truck-route-planner/1.0 (https://github.com/akhilofindia/geo-routing)"
NWS_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/geo+json"}
_CACHE: dict[str, tuple[float, Hourly]] = {}
_CACHE_SECONDS = 60 * 60
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
    found = _fetch_nws(unique)
    if len(found) >= max(1, len(unique) // 4):
        return found
    days = max(1, min(16, int(forecast_days)))
    try:
        fallback = {}
        for start in range(0, len(unique), CHUNK_SIZE):
            fallback.update(_fetch_chunk(unique[start : start + CHUNK_SIZE], days))
    except WeatherError:
        if found:
            return found
        raise
    found.update(fallback)
    return found


def duration_hours(spec: str) -> int:
    """Hours covered by an NWS validTime duration such as PT3H or P1DT6H."""
    days = int(re.search(r"(\d+)D", spec).group(1)) if re.search(r"(\d+)D", spec) else 0
    hours = int(re.search(r"(\d+)H", spec).group(1)) if re.search(r"(\d+)H", spec) else 0
    minutes = int(re.search(r"(\d+)M", spec).group(1)) if re.search(r"(\d+)M", spec) else 0
    return max(1, days * 24 + hours + (1 if minutes >= 30 else 0))


def nws_series(block: dict, kind: str) -> dict[datetime, float]:
    """Map an NWS grid series onto UTC hours. Wind is mph. Rain and snow are inches per hour."""
    uom = str(block.get("uom") or "")
    series: dict[datetime, float] = {}
    for item in block.get("values") or []:
        stamp, _, duration = str(item.get("validTime") or "").partition("/")
        value = _number(item.get("value"))
        if not stamp or value is None:
            continue
        start = datetime.fromisoformat(stamp).astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        span = duration_hours(duration or "PT1H")
        amount = _nws_amount(value, uom, kind, span)
        for offset in range(min(span, 24 * 8)):
            series[start + timedelta(hours=offset)] = amount
    return series


def hourly_from_nws(wind: dict[datetime, float], rain: dict[datetime, float], snow: dict[datetime, float]) -> Hourly | None:
    if not wind:
        return None
    start = min(wind)
    end = max(wind)
    times: list[datetime] = []
    winds: list[float] = []
    rains: list[float] = []
    snows: list[float] = []
    hour = start
    while hour <= end and len(times) < 24 * 8:
        times.append(hour)
        winds.append(wind.get(hour, 0.0))
        rains.append(rain.get(hour, 0.0))
        snows.append(snow.get(hour, 0.0))
        hour += timedelta(hours=1)
    return Hourly(times, winds, rains, snows)


def _nws_amount(value: float, uom: str, kind: str, span: int) -> float:
    if kind == "wind":
        if "km_h" in uom:
            return value * 0.621371
        if "m_s" in uom:
            return value * 2.23694
        return value
    per_hour = value / span
    if "mm" in uom:
        return per_hour / 25.4
    return per_hour


def _fetch_nws(points: list[tuple[float, float]]) -> dict[tuple[float, float], Hourly]:
    with ThreadPoolExecutor(max_workers=4) as pool:
        located = list(pool.map(_nws_grid_url, points))
    groups: dict[str, list[tuple[float, float]]] = {}
    for point, url in zip(points, located):
        if url:
            groups.setdefault(url, []).append(point)
    if not groups:
        return {}
    parsed: dict[tuple[float, float], Hourly] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        loaded = pool.map(_cached_grid, list(groups))
        for url, hourly in zip(groups, loaded):
            if hourly is None:
                continue
            for point in groups[url]:
                parsed[point] = hourly
    return parsed


def _nws_grid_url(point: tuple[float, float]) -> str | None:
    lat, lon = point
    try:
        response = requests.get(
            f"{NWS_POINTS_URL}/{lat:.4f},{lon:.4f}",
            headers=NWS_HEADERS,
            timeout=20,
        )
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    try:
        url = response.json()["properties"]["forecastGridData"]
    except (ValueError, KeyError, TypeError):
        return None
    return str(url) if url else None


def _cached_grid(url: str) -> Hourly | None:
    cached = _CACHE.get(url)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_SECONDS:
        return cached[1]
    try:
        response = requests.get(url, headers=NWS_HEADERS, timeout=30)
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    try:
        props = response.json()["properties"]
    except (ValueError, KeyError, TypeError):
        return None
    hourly = hourly_from_nws(
        nws_series(props.get("windSpeed") or {}, "wind"),
        nws_series(props.get("quantitativePrecipitation") or {}, "precip"),
        nws_series(props.get("snowfallAmount") or {}, "precip"),
    )
    if hourly is not None:
        _CACHE[url] = (now, hourly)
    return hourly


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
