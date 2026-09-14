"""Coverage: ZIP-trusted geo, street-name false matches, list_date fallback."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from scanner.config import load_config
from scanner.geo import classify_town, within_town_radius
from scanner.new_listings import compile_new_listings
from scanner.normalize import normalize_realtor_record


def _cfg() -> dict:
    config = load_config()
    config["_include_optional"] = True
    config.setdefault("scan", {})["include_optional_towns"] = True
    return config


def test_oswego_zip_kept_beyond_three_mile_circle():
    config = _cfg()
    rec = {
        "address": "1502 Cherry Rd",
        "city": "Oswego",
        "zip": "60543",
        "lat": 41.7200,
        "lon": -88.2800,
        "coords_source": "listing",
    }
    town, _ = classify_town(rec, config)
    assert town == "Oswego"
    assert within_town_radius(rec, town, config) is True


def test_wheaton_zip_bleed_still_radius_gated():
    config = _cfg()
    rec = {
        "address": "100 Fake St",
        "city": "Wheaton",
        "zip": "60188",
        "lat": 41.9120,
        "lon": -88.1420,
        "coords_source": "listing",
    }
    town, _ = classify_town(rec, config)
    assert town == "Wheaton"
    assert within_town_radius(rec, town, config) is False


def test_somonauk_street_in_sycamore_is_not_somonauk():
    config = _cfg()
    rec = {
        "address": "726 Somonauk St",
        "city": "Sycamore",
        "zip": "60178",
    }
    town, _ = classify_town(rec, config)
    assert town is None


def test_sheridan_street_in_lostant_is_not_sheridan():
    config = _cfg()
    rec = {
        "address": "101 S Sheridan St",
        "city": "Lostant",
        "zip": "61334",
    }
    town, _ = classify_town(rec, config)
    assert town is None


def test_blank_city_uses_configured_zip():
    config = _cfg()
    rec = {"address": "607 Searl St", "city": "", "zip": "60545"}
    town, _ = classify_town(rec, config)
    assert town == "Plano"


def test_aurora_in_oswego_zip_classifies_oswego():
    config = _cfg()
    rec = {"address": "1 Main St", "city": "Aurora", "zip": "60543"}
    town, _ = classify_town(rec, config)
    assert town == "Oswego"


def test_normalize_list_date_falls_back_to_status_change():
    rec = normalize_realtor_record({
        "list_date": None,
        "last_status_change_date": "2026-09-12T14:00:00Z",
        "location": {"address": {"line": "1 Main", "city": "Oswego", "postal_code": "60543"}},
    })
    assert rec["list_date"] == "2026-09-12T14:00:00Z"


def test_compile_new_listings_keeps_far_oswego_and_status_change_date():
    config = _cfg()
    listed = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = [
        {
            "property_id": "far-oswego",
            "list_date": listed,
            "status": "for_sale",
            "list_price": 400000,
            "location": {
                "address": {
                    "line": "1502 Cherry Rd",
                    "city": "Oswego",
                    "state_code": "IL",
                    "postal_code": "60543",
                    "coordinate": {"lat": 41.7200, "lon": -88.2800},
                }
            },
            "description": {"type": "single_family", "text": "Home"},
        },
        {
            "property_id": "status-only",
            "list_date": None,
            "last_status_change_date": listed,
            "status": "for_sale",
            "list_price": 250000,
            "location": {
                "address": {
                    "line": "510 N Lafayette St",
                    "city": "Sandwich",
                    "state_code": "IL",
                    "postal_code": "60548",
                }
            },
            "description": {"type": "single_family", "text": "Home"},
        },
    ]
    records, stats = compile_new_listings(raw, config=config, days=7)
    ids = {r["property_id"] for r in records}
    assert "far-oswego" in ids
    assert "status-only" in ids
    assert stats["final_count"] == 2
