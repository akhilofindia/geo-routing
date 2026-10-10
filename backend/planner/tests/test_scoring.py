from planner.scoring import explain, rank_routes, summarize


def _checkpoint(mile: float, level: str) -> dict:
    return {"mile": mile, "level": level}


def test_segment_miles_use_the_worse_endpoint():
    summary = summarize(
        [
            _checkpoint(0, "low"),
            _checkpoint(25, "severe"),
            _checkpoint(50, "low"),
        ]
    )
    assert summary["severe_mi"] == 50
    assert summary["low_mi"] == 0
    assert summary["avg_risk"] == 4


def test_unknown_segments_are_left_out_of_the_average():
    summary = summarize(
        [
            _checkpoint(0, "low"),
            _checkpoint(10, "unknown"),
            _checkpoint(30, "high"),
        ]
    )
    assert summary["unknown_mi"] == 30
    assert summary["low_mi"] == 0
    assert summary["high_mi"] == 0
    assert summary["avg_risk"] is None


def test_ranking_order():
    routes = [
        _route("Route A", no_travel=10, severe=0, high=0, average=5, duration=100),
        _route("Route B", no_travel=0, severe=50, high=0, average=4, duration=200),
        _route("Route C", no_travel=0, severe=50, high=10, average=3, duration=50),
        _route("Route D", no_travel=0, severe=50, high=0, average=4.5, duration=10),
        _route("Route E", no_travel=0, severe=40, high=80, average=3.5, duration=400),
    ]
    ranked = rank_routes(routes)
    assert [route["label"] for route in ranked] == [
        "Route E",
        "Route B",
        "Route D",
        "Route C",
        "Route A",
    ]
    assert ranked[0]["recommended"] is True
    assert all(route["recommended"] is False for route in ranked[1:])


def test_duration_breaks_a_weather_tie():
    routes = [
        _route("Route A", no_travel=0, severe=5, high=5, average=2, duration=180),
        _route("Route B", no_travel=0, severe=5, high=5, average=2, duration=90),
    ]
    ranked = rank_routes(routes)
    assert ranked[0]["label"] == "Route B"
    text = explain(ranked)
    assert "shortest" in text
    assert "Route B" in text


def test_explanation_names_the_deciding_miles():
    routes = rank_routes(
        [
            _route("Route 1", no_travel=0, severe=40, high=10, average=3, duration=100),
            _route("Route 2", no_travel=0, severe=12, high=30, average=2.4, duration=130),
            _route("Route 3", no_travel=0, severe=28, high=5, average=2.2, duration=90),
        ]
    )
    text = explain(routes)
    assert text.startswith("Route 2 is recommended")
    assert "severe miles" in text
    assert "12" in text


def _route(label: str, no_travel: float, severe: float, high: float, average: float, duration: float) -> dict:
    return {
        "label": label,
        "duration_min": duration,
        "recommended": False,
        "summary": {
            "no_travel_mi": no_travel,
            "severe_mi": severe,
            "high_mi": high,
            "moderate_mi": 0,
            "low_mi": 0,
            "unknown_mi": 0,
            "avg_risk": average,
        },
    }
