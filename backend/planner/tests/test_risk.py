from planner.risk import (
    apply_load_to_wind,
    checkpoint_risk,
    classify_rain,
    classify_snow,
    classify_wind,
)


def test_wind_band_edges():
    assert classify_wind(24.9) == "low"
    assert classify_wind(25) == "moderate"
    assert classify_wind(34.9) == "moderate"
    assert classify_wind(35) == "high"
    assert classify_wind(44.9) == "high"
    assert classify_wind(45) == "severe"
    assert classify_wind(54.9) == "severe"
    assert classify_wind(55) == "no_travel"


def test_rain_band_edges():
    assert classify_rain(0.09) == "low"
    assert classify_rain(0.10) == "moderate"
    assert classify_rain(0.249) == "moderate"
    assert classify_rain(0.25) == "high"
    assert classify_rain(0.499) == "high"
    assert classify_rain(0.50) == "severe"
    assert classify_rain(1.00) == "severe"
    assert classify_rain(1.01) == "no_travel"


def test_snow_band_edges():
    assert classify_snow(0.49) == "low"
    assert classify_snow(0.5) == "moderate"
    assert classify_snow(0.99) == "moderate"
    assert classify_snow(1) == "high"
    assert classify_snow(1.99) == "high"
    assert classify_snow(2) == "severe"
    assert classify_snow(3) == "severe"
    assert classify_snow(3.01) == "no_travel"


def test_load_does_not_change_wind_at_the_boundary_weights():
    assert apply_load_to_wind(50, 30_000) == "severe"
    assert apply_load_to_wind(40, 40_000) == "high"
    assert apply_load_to_wind(20, 80_000) == "low"


def test_load_upgrades_wind_only_inside_the_stated_bands():
    assert apply_load_to_wind(55, 1_000) == "no_travel"
    assert apply_load_to_wind(54.9, 30_001) == "no_travel"
    assert apply_load_to_wind(45, 30_001) == "no_travel"
    assert apply_load_to_wind(44.9, 40_001) == "severe"
    assert apply_load_to_wind(35, 40_001) == "severe"
    assert apply_load_to_wind(34.9, 80_000) == "moderate"
    assert apply_load_to_wind(50, 30_001) == "no_travel"


def test_checkpoint_uses_the_worst_condition():
    risk = checkpoint_risk(wind_mph=10, rain_in_hr=0.30, snow_in_hr=0.6, load_lb=10_000)
    assert risk["wind_level"] == "low"
    assert risk["rain_level"] == "high"
    assert risk["snow_level"] == "moderate"
    assert risk["level"] == "high"


def test_heavy_load_can_set_the_checkpoint_level():
    risk = checkpoint_risk(wind_mph=40, rain_in_hr=0, snow_in_hr=0, load_lb=40_001)
    assert risk["wind_level"] == "severe"
    assert risk["level"] == "severe"
    assert any("raised" in reason for reason in risk["reasons"])
