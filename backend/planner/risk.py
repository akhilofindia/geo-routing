"""Weather bands and load upgrades for a truck checkpoint."""

from __future__ import annotations

LEVELS = ("low", "moderate", "high", "severe", "no_travel")
LEVEL_SCORE = {
    "low": 1,
    "moderate": 2,
    "high": 3,
    "severe": 4,
    "no_travel": 5,
}
LEVEL_RANK = {name: index for index, name in enumerate(LEVELS)}


def classify_wind(mph: float) -> str:
    """Map sustained wind to a band. Severe stops just below 55 mph."""
    if mph < 25:
        return "low"
    if mph < 35:
        return "moderate"
    if mph < 45:
        return "high"
    if mph < 55:
        return "severe"
    return "no_travel"


def classify_rain(inches_per_hour: float) -> str:
    """Map liquid precipitation rate. 1.00 in/hr is still severe."""
    if inches_per_hour < 0.10:
        return "low"
    if inches_per_hour < 0.25:
        return "moderate"
    if inches_per_hour < 0.50:
        return "high"
    if inches_per_hour <= 1.00:
        return "severe"
    return "no_travel"


def classify_snow(inches_per_hour: float) -> str:
    """Map snowfall rate. 3.0 in/hr is still severe."""
    if inches_per_hour < 0.5:
        return "low"
    if inches_per_hour < 1.0:
        return "moderate"
    if inches_per_hour < 2.0:
        return "high"
    if inches_per_hour <= 3.0:
        return "severe"
    return "no_travel"


def apply_load_to_wind(mph: float, load_lb: float) -> str:
    """Classify wind, then raise the band when the load rules say so.

    Load does not change rain or snow. The upgrades follow the wind bands:
    45–54 mph with more than 30,000 lb becomes no-travel, and 35–44 mph
    with more than 40,000 lb becomes severe. 55 mph and above is no-travel
    for every load.
    """
    if 45 <= mph < 55 and load_lb > 30_000:
        return "no_travel"
    if 35 <= mph < 45 and load_lb > 40_000:
        return "severe"
    return classify_wind(mph)


def worse(left: str, right: str) -> str:
    """Return the more severe level. Unknown on either side stays unknown."""
    if left == "unknown" or right == "unknown":
        return "unknown"
    if LEVEL_RANK[left] >= LEVEL_RANK[right]:
        return left
    return right


def checkpoint_risk(
    wind_mph: float,
    rain_in_hr: float,
    snow_in_hr: float,
    load_lb: float,
) -> dict:
    """Score one checkpoint. The level is the worst of the three conditions."""
    base_wind = classify_wind(wind_mph)
    wind_level = apply_load_to_wind(wind_mph, load_lb)
    rain_level = classify_rain(rain_in_hr)
    snow_level = classify_snow(snow_in_hr)
    level = wind_level
    for candidate in (rain_level, snow_level):
        level = worse(level, candidate)

    reasons: list[str] = []
    if wind_level != "low":
        note = f"Wind {wind_mph:.1f} mph ({_label(wind_level)})"
        if wind_level != base_wind:
            note += f", raised for a {load_lb:,.0f} lb load"
        reasons.append(note)
    if rain_level != "low":
        reasons.append(f"Rain {rain_in_hr:.2f} in/hr ({_label(rain_level)})")
    if snow_level != "low":
        reasons.append(f"Snow {snow_in_hr:.2f} in/hr ({_label(snow_level)})")
    if not reasons:
        reasons.append("Wind, rain, and snow are in the low band")

    return {
        "wind_level": wind_level,
        "rain_level": rain_level,
        "snow_level": snow_level,
        "level": level,
        "reasons": reasons,
    }


def _label(level: str) -> str:
    return level.replace("_", " ")
