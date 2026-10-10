from planner.geometry import (
    cumulative_miles,
    decode_polyline,
    encode_polyline,
    haversine_miles,
    vertex_times,
)
from planner.sampling import sample_checkpoints


def test_polyline_roundtrip():
    points = [(32.7767, -96.7970), (31.9686, -99.9018), (30.2672, -97.7431)]
    assert decode_polyline(encode_polyline(points), precision=6) == [
        (round(lat, 6), round(lon, 6)) for lat, lon in points
    ]


def test_maneuver_times_follow_each_stretch():
    points = [(30.0, -96.0), (30.1, -96.0), (30.2, -96.0)]
    maneuvers = [
        {"begin_shape_index": 0, "end_shape_index": 1, "time": 100},
        {"begin_shape_index": 1, "end_shape_index": 2, "time": 300},
    ]
    times = vertex_times(points, maneuvers, duration_sec=400)
    assert times == [0.0, 100.0, 400.0]

    cumulative = cumulative_miles(points)
    samples = sample_checkpoints(points, times, interval_miles=cumulative[-1] / 2)
    midpoint = samples[1]
    assert abs(midpoint["mile"] - cumulative[-1] / 2) < 0.05
    assert abs(midpoint["offset_sec"] - 100) < 1


def test_checkpoint_spacing_and_eta_along_a_meridian():
    points = [(30 + index * 0.1, -96.0) for index in range(11)]
    cumulative = cumulative_miles(points)
    total = cumulative[-1]
    duration = 7200.0
    times = [duration * mile / total for mile in cumulative]
    expected_step = haversine_miles(points[0], points[1]) * 10
    assert abs(total - expected_step) < 0.01

    samples = sample_checkpoints(points, times, interval_miles=25)
    miles = [sample["mile"] for sample in samples]
    assert miles[0] == 0
    assert abs(miles[1] - 25) < 0.05
    assert abs(miles[2] - 50) < 0.05
    assert abs(miles[-1] - total) < 0.05
    assert miles[-1] != miles[-2]
    assert abs(samples[1]["offset_sec"] - duration * (25 / total)) < 2
    assert abs(samples[-1]["offset_sec"] - duration) < 1


def test_short_route_still_has_both_ends():
    points = [(30.0, -96.0), (30.05, -96.0)]
    times = [0.0, 600.0]
    samples = sample_checkpoints(points, times, interval_miles=50)
    assert len(samples) == 2
    assert samples[0]["mile"] == 0
    assert samples[1]["offset_sec"] == 600
