"""Place search through the Open-Meteo geocoder."""

from __future__ import annotations

import requests

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
USER_AGENT = "truck-route-planner/1.0"

# State names are not cities, so the geocoder returns towns that share the name.
# Each point is a major city on the road network inside that state.
US_STATES: dict[str, tuple[str, float, float]] = {
    "alabama": ("Alabama, United States", 33.5207, -86.8025),
    "alaska": ("Alaska, United States", 61.2181, -149.9003),
    "arizona": ("Arizona, United States", 33.4484, -112.0740),
    "arkansas": ("Arkansas, United States", 34.7465, -92.2896),
    "california": ("California, United States", 34.0522, -118.2437),
    "colorado": ("Colorado, United States", 39.7392, -104.9903),
    "connecticut": ("Connecticut, United States", 41.7658, -72.6734),
    "delaware": ("Delaware, United States", 39.7391, -75.5398),
    "florida": ("Florida, United States", 25.7617, -80.1918),
    "georgia": ("Georgia, United States", 33.7490, -84.3880),
    "hawaii": ("Hawaii, United States", 21.3069, -157.8583),
    "idaho": ("Idaho, United States", 43.6150, -116.2023),
    "illinois": ("Illinois, United States", 41.8781, -87.6298),
    "indiana": ("Indiana, United States", 39.7684, -86.1581),
    "iowa": ("Iowa, United States", 41.5868, -93.6250),
    "kansas": ("Kansas, United States", 37.6872, -97.3301),
    "kentucky": ("Kentucky, United States", 38.2527, -85.7585),
    "louisiana": ("Louisiana, United States", 29.9511, -90.0715),
    "maine": ("Maine, United States", 43.6591, -70.2568),
    "maryland": ("Maryland, United States", 39.2904, -76.6122),
    "massachusetts": ("Massachusetts, United States", 42.3601, -71.0589),
    "michigan": ("Michigan, United States", 42.3314, -83.0458),
    "minnesota": ("Minnesota, United States", 44.9778, -93.2650),
    "mississippi": ("Mississippi, United States", 32.2988, -90.1848),
    "missouri": ("Missouri, United States", 38.6270, -90.1994),
    "montana": ("Montana, United States", 45.7833, -108.5007),
    "nebraska": ("Nebraska, United States", 41.2565, -95.9345),
    "nevada": ("Nevada, United States", 36.1699, -115.1398),
    "new hampshire": ("New Hampshire, United States", 42.9956, -71.4548),
    "new jersey": ("New Jersey, United States", 40.7357, -74.1724),
    "new mexico": ("New Mexico, United States", 35.0844, -106.6504),
    "new york": ("New York, United States", 40.7128, -74.0060),
    "north carolina": ("North Carolina, United States", 35.2271, -80.8431),
    "north dakota": ("North Dakota, United States", 46.8772, -96.7898),
    "ohio": ("Ohio, United States", 39.9612, -82.9988),
    "oklahoma": ("Oklahoma, United States", 35.4676, -97.5164),
    "oregon": ("Oregon, United States", 45.5152, -122.6784),
    "pennsylvania": ("Pennsylvania, United States", 39.9526, -75.1652),
    "rhode island": ("Rhode Island, United States", 41.8240, -71.4128),
    "south carolina": ("South Carolina, United States", 32.7765, -79.9311),
    "south dakota": ("South Dakota, United States", 43.5460, -96.7313),
    "tennessee": ("Tennessee, United States", 36.1627, -86.7816),
    "texas": ("Texas, United States", 29.7604, -95.3698),
    "utah": ("Utah, United States", 40.7608, -111.8910),
    "vermont": ("Vermont, United States", 44.4759, -73.2121),
    "virginia": ("Virginia, United States", 36.8529, -75.9780),
    "washington": ("Washington, United States", 47.6062, -122.3321),
    "west virginia": ("West Virginia, United States", 38.3498, -81.6326),
    "wisconsin": ("Wisconsin, United States", 43.0389, -87.9065),
    "wyoming": ("Wyoming, United States", 41.1400, -104.8202),
    "district of columbia": ("District of Columbia, United States", 38.9072, -77.0369),
}


class GeocodeError(Exception):
    def __init__(self, message: str, *, status: int = 502):
        super().__init__(message)
        self.status = status


def matching_states(query: str) -> list[dict]:
    """US states whose name is the query, or starts with a query of 4+ letters."""
    text = " ".join(query.lower().split())
    head = text.split(",")[0].strip()
    exact = []
    prefixed = []
    for name, (label, latitude, longitude) in US_STATES.items():
        place = {"label": label, "latitude": latitude, "longitude": longitude}
        if head == name or text == name:
            exact.append(place)
        elif len(head) >= 4 and name.startswith(head):
            prefixed.append(place)
    return exact or prefixed


def search(query: str, count: int = 5) -> list[dict]:
    try:
        response = requests.get(
            GEOCODE_URL,
            params={"name": query, "count": max(count, 10), "language": "en", "format": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=12,
        )
    except requests.Timeout as exc:
        raise GeocodeError("Place search timed out. Try again in a moment.", status=504) from exc
    except requests.RequestException as exc:
        raise GeocodeError("Place search did not respond. Try again in a moment.", status=502) from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise GeocodeError("Place search returned an unreadable response.", status=502) from exc
    if response.status_code == 429:
        raise GeocodeError("Place search is busy. Try again in a moment.", status=503)
    if response.status_code >= 500:
        raise GeocodeError("Place search is unavailable. Try again in a moment.", status=502)
    if response.status_code >= 400 or not isinstance(payload, dict):
        raise GeocodeError("Place search rejected that query.", status=400)

    ranked = sorted(payload.get("results") or [], key=_place_rank)
    results = []
    seen: set[tuple[float, float]] = set()
    for place in matching_states(query):
        _add_place(results, seen, place)
    for item in ranked:
        label_parts = [item.get("name") or ""]
        if item.get("admin1"):
            label_parts.append(item["admin1"])
        if item.get("country"):
            label_parts.append(item["country"])
        _add_place(
            results,
            seen,
            {
                "label": ", ".join(part for part in label_parts if part),
                "latitude": item["latitude"],
                "longitude": item["longitude"],
            },
        )
        if len(results) >= count:
            break
    return results[:count]


def _place_rank(item: dict) -> tuple[int, int]:
    country = 0 if item.get("country_code") == "US" else 1
    population = int(item.get("population") or 0)
    return (country, -population)


def _add_place(results: list[dict], seen: set[tuple[float, float]], place: dict) -> None:
    key = (round(place["latitude"], 2), round(place["longitude"], 2))
    if key in seen:
        return
    seen.add(key)
    results.append(place)
