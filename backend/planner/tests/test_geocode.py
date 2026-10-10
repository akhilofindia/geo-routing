from planner.geocode import matching_states
from planner.geometry import haversine_miles
from planner.routing import section_targets, via_candidates


def test_california_matches_the_state_not_a_town():
    matches = matching_states("california")
    assert [place["label"] for place in matches] == ["California, United States"]
    assert matches[0]["latitude"] == 34.0522
    assert matches[0]["longitude"] == -118.2437


def test_state_prefix_needs_four_letters():
    assert matching_states("cal") == []
    assert matching_states("calif")[0]["label"] == "California, United States"


def test_offset_via_stays_clear_of_the_routes_already_found():
    north = [(35.0, -110.0 + index * 0.5) for index in range(16)]
    south = [(33.2, -110.0 + index * 0.5) for index in range(16)]
    candidates = via_candidates([{"points": north}, {"points": south}])
    assert candidates
    for point in candidates:
        gap = min(
            haversine_miles(point, place)
            for route in (north, south)
            for place in route
        )
        assert gap >= 45


def test_long_trip_is_split_under_the_router_cap():
    targets = section_targets(1560)
    assert targets[0] == 0
    assert targets[-1] == 1560
    gaps = [right - left for left, right in zip(targets, targets[1:])]
    assert gaps
    assert max(gaps) <= 600
