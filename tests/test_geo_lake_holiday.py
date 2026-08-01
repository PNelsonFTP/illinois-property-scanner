"""Lake Holiday street classification — Wildwood/Sandwich ≠ Sheridan."""

from __future__ import annotations

from scanner.geo import classify_town, is_lake_holiday_area


OPTIONAL_CFG = {
    "scan": {"include_optional_towns": True},
    "_include_optional": True,
    "towns": {
        "Lake Holiday": {"county": "LaSalle", "cities": ["lake holiday"]},
        "Sandwich": {"county": "DeKalb", "cities": ["sandwich"]},
    },
    "optional_towns": {
        "Sheridan": {"county": "LaSalle", "cities": ["sheridan"]},
    },
}


def test_wildwood_cardinal_sandwich_is_lake_holiday():
    rec = {"address": "120 Cardinal Ln Unit A", "city": "Sandwich"}
    assert is_lake_holiday_area(rec) is True
    town, county = classify_town(rec, OPTIONAL_CFG)
    assert town == "Lake Holiday"
    assert county == "LaSalle"


def test_cedar_ln_sandwich_is_lake_holiday():
    rec = {"address": "20 Cedar Ln", "city": "Sandwich"}
    town, _ = classify_town(rec, OPTIONAL_CFG)
    assert town == "Lake Holiday"


def test_sheridan_is_separate_optional_town():
    rec = {"address": "100 N Main St", "city": "Sheridan"}
    assert is_lake_holiday_area(rec) is False
    town, county = classify_town(rec, OPTIONAL_CFG)
    assert town == "Sheridan"
    assert county == "LaSalle"


def test_sheridan_excluded_when_optional_off():
    cfg = {
        "scan": {"include_optional_towns": False},
        "_include_optional": False,
    }
    town, county = classify_town({"address": "100 N Main St", "city": "Sheridan"}, cfg)
    assert town is None
    assert county is None
