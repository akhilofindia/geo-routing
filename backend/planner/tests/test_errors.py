from planner.routing import RoutingError, describe_osrm_failure, describe_valhalla_failure, prefer_routing_error
from datetime import datetime, timedelta, timezone

from planner.weather import describe_weather_reason, limit_locations, nws_series
from planner.planning import PlanError, plan_trip


def test_distance_limit_is_not_a_dead_router():
    error = describe_valhalla_failure("Path distance exceeds the max distance limit: 1500000 meters", 154, 400)
    assert error.code == "distance"
    assert error.status == 400
    assert "longer than the truck router" in str(error)
    assert "did not respond" not in str(error)


def test_no_road_and_off_road_are_specific():
    no_road = describe_valhalla_failure("No path could be found", 442, 400)
    off_road = describe_valhalla_failure("No suitable edges near location", 171, 400)
    assert str(no_road) == "No drivable road connects those places."
    assert str(off_road) == "One of those places is not close enough to a drivable road."
    assert describe_osrm_failure("NoRoute", 400).code == "no_route"
    assert describe_osrm_failure("NoSegment", 400).code == "off_road"


def test_backup_failure_keeps_the_geographic_reason():
    primary = describe_valhalla_failure("No path could be found", 442, 400)
    fallback = RoutingError("The routing service timed out. Try again in a moment.", status=504, code="timeout")
    chosen = prefer_routing_error(primary, fallback)
    assert "No truck route connects those places" in str(chosen)
    assert "timed out" in str(chosen)
    assert chosen.status == 504


def test_no_road_from_the_backup_replaces_a_distance_limit():
    primary = describe_valhalla_failure("Path distance exceeds the max distance limit", 154, 400)
    fallback = describe_osrm_failure("NoRoute", 400)
    chosen = prefer_routing_error(primary, fallback)
    assert str(chosen) == "No drivable road connects those places."
    assert chosen.status == 400


def test_two_outages_say_the_service_did_not_respond():
    primary = RoutingError("The truck router timed out. Try again in a moment.", status=504, code="timeout")
    fallback = RoutingError("The routing service did not respond. Try again in a moment.", status=502, code="down")
    chosen = prefer_routing_error(primary, fallback)
    assert str(chosen) == "The routing service did not respond. Try again in a moment."


def test_weather_reasons_stay_specific():
    assert "about an hour" in describe_weather_reason("Hourly API request limit exceeded")
    assert "per minute" in describe_weather_reason("Minutely API request limit exceeded")
    assert "tomorrow" in describe_weather_reason("Daily API request limit exceeded")
    assert "outside the area" in describe_weather_reason("Parameter latitude is invalid")


def test_nws_wind_and_rain_units():
    hour = datetime(2026, 10, 10, 5, tzinfo=timezone.utc)
    wind = nws_series(
        {"uom": "wmoUnit:km_h-1", "values": [{"validTime": "2026-10-10T05:00:00+00:00/PT2H", "value": 10}]},
        "wind",
    )
    rain = nws_series(
        {"uom": "wmoUnit:mm", "values": [{"validTime": "2026-10-10T05:00:00+00:00/PT3H", "value": 25.4}]},
        "precip",
    )
    assert abs(wind[hour] - 6.21371) < 0.01
    assert hour + timedelta(hours=1) in wind
    assert abs(rain[hour] - (1 / 3)) < 0.01


def test_long_corridor_stays_within_the_lookup_budget():
    points = [(32.0 + index * 0.05, -97.0 - index * 0.08) for index in range(800)]
    limited = limit_locations(points, forecast_days=4)
    assert len(limited) <= 80
    assert limited


def test_input_edge_cases_name_the_problem():
    cases = [
        ({}, "Enter an origin."),
        ({"origin": "   ", "destination": "Dallas"}, "Enter an origin."),
        (
            {
                "origin": {"label": "A", "latitude": 0, "longitude": 0},
                "destination": {"label": "B", "latitude": 0, "longitude": 0.01},
                "departure": "2026-10-10T12:00:00+00:00",
                "load_lb": 35000,
                "sample_miles": 25,
            },
            "at least a mile apart",
        ),
        (
            {
                "origin": {"label": "A", "latitude": 32.7, "longitude": -96.8},
                "destination": {"label": "B", "latitude": 34.0, "longitude": -118.2},
                "departure": "tomorrow",
                "load_lb": 35000,
                "sample_miles": 25,
            },
            "Departure time could not be read.",
        ),
        (
            {
                "origin": {"label": "A", "latitude": 32.7, "longitude": -96.8},
                "destination": {"label": "B", "latitude": 34.0, "longitude": -118.2},
                "departure": "2026-10-10T12:00:00+00:00",
                "load_lb": 900000,
                "sample_miles": 25,
            },
            "between 0 and 200,000",
        ),
        (
            {
                "origin": {"label": "A", "latitude": 95, "longitude": -96.8},
                "destination": {"label": "B", "latitude": 34.0, "longitude": -118.2},
                "departure": "2026-10-10T12:00:00+00:00",
                "load_lb": 1000,
                "sample_miles": 25,
            },
            "coordinates are out of range",
        ),
    ]
    for payload, expected in cases:
        try:
            plan_trip(payload)
        except PlanError as exc:
            assert expected in str(exc)
            assert exc.status == 400
        else:
            raise AssertionError(f"expected an error containing {expected}")
