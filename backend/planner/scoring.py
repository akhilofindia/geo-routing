"""Segment miles, average risk, and the route recommendation order."""

from __future__ import annotations

from planner.risk import LEVEL_SCORE, worse


def summarize(checkpoints: list[dict]) -> dict:
    """Miles by level. A segment takes the worse of its two checkpoints.

    Unknown endpoints are left out of the scored totals and out of the average.
    """
    buckets = {
        "low": 0.0,
        "moderate": 0.0,
        "high": 0.0,
        "severe": 0.0,
        "no_travel": 0.0,
        "unknown": 0.0,
    }
    weighted = 0.0
    known = 0.0
    for start, end in zip(checkpoints, checkpoints[1:]):
        miles = float(end["mile"]) - float(start["mile"])
        if miles <= 0:
            continue
        level = worse(start["level"], end["level"])
        buckets[level] = buckets.get(level, 0.0) + miles
        if level != "unknown":
            weighted += LEVEL_SCORE[level] * miles
            known += miles
    average = (weighted / known) if known else None
    return {
        "no_travel_mi": round(buckets["no_travel"], 2),
        "severe_mi": round(buckets["severe"], 2),
        "high_mi": round(buckets["high"], 2),
        "moderate_mi": round(buckets["moderate"], 2),
        "low_mi": round(buckets["low"], 2),
        "unknown_mi": round(buckets["unknown"], 2),
        "avg_risk": round(average, 3) if average is not None else None,
    }


def rank_routes(routes: list[dict]) -> list[dict]:
    """Prefer no-travel miles, then severe, high, average risk, then duration.

    No-travel miles lead the written severe/high/average/time order so a
    banned stretch cannot outrank a route that is only severe. Routes with
    no scored miles sort after routes that have a forecast.
    """

    def sort_key(item: tuple[int, dict]) -> tuple:
        index, route = item
        summary = route["summary"]
        average = summary["avg_risk"]
        return (
            0 if average is not None else 1,
            summary["no_travel_mi"],
            summary["severe_mi"],
            summary["high_mi"],
            average if average is not None else 0,
            route["duration_min"],
            index,
        )

    ordered = [route for _index, route in sorted(enumerate(routes), key=sort_key)]
    for route in ordered:
        route["recommended"] = False
    if ordered:
        ordered[0]["recommended"] = True
    return ordered


def explain(ranked: list[dict]) -> str:
    """One sentence naming the criterion that separated the winner."""
    winner = ranked[0]
    label = winner["label"]
    if len(ranked) == 1:
        return f"{label} is the only distinct route returned."
    if winner["summary"]["avg_risk"] is None:
        return (
            f"{label} is recommended because it is the shortest trip "
            f"({_fmt_duration(winner['duration_min'])}). Weather for these routes "
            "falls outside the forecast, so risk miles were not scored."
        )

    checks = (
        ("no_travel_mi", "no-travel miles", "fewest"),
        ("severe_mi", "severe miles", "fewest"),
        ("high_mi", "high-risk miles", "fewest"),
        ("avg_risk", "average risk", "lowest"),
    )
    for field, name, word in checks:
        numbers = [_metric(route, field) for route in ranked]
        best = numbers[0]
        if best is None or any(other is None for other in numbers[1:]):
            continue
        if all(best < other for other in numbers[1:]):
            shown = _fmt_metric(best, field)
            compared = ", ".join(
                f"{route['label']} ({_fmt_metric(numbers[index], field)})"
                for index, route in enumerate(ranked[1:], start=1)
            )
            return (
                f"{label} is recommended because it has the {word} {name} "
                f"({shown}), compared with {compared}."
            )

    durations = [route["duration_min"] for route in ranked]
    if all(durations[0] < other for other in durations[1:]):
        return (
            f"{label} is recommended because weather risk matches the other routes "
            f"and it is the shortest trip ({_fmt_duration(durations[0])})."
        )
    return f"{label} is recommended. It ties the other routes on weather risk and travel time."


def _metric(route: dict, field: str) -> float | None:
    if field == "duration_min":
        return route["duration_min"]
    return route["summary"][field]


def _fmt_metric(value: float, field: str) -> str:
    if field == "avg_risk":
        return f"{value:.2f}"
    return _fmt_miles(value)


def _fmt_miles(value: float) -> str:
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return f"{value:.1f}"


def _fmt_duration(minutes: float) -> str:
    total = int(round(minutes))
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f"{hours} h {mins} min"
    if hours:
        return f"{hours} h"
    return f"{mins} min"
