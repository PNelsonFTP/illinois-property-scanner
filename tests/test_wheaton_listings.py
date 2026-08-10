"""Tests for Wheaton all-for-sale compile filters."""

from __future__ import annotations

from scanner.wheaton_listings import compile_wheaton_listings


def _raw(
    *,
    city: str = "Wheaton",
    state: str = "IL",
    zip_code: str = "60187",
    status: str = "for_sale",
    address: str = "100 Main St",
    lat: float = 41.8661,
    lon: float = -88.1070,
    property_id: str = "w-1",
):
    return {
        "description": {"text": "Nice home in Wheaton.", "type": "single_family"},
        "location": {
            "address": {
                "line": address,
                "city": city,
                "state_code": state,
                "postal_code": zip_code,
                "coordinate": {"lat": lat, "lon": lon},
            }
        },
        "list_price": 450000,
        "status": status,
        "flags": {},
        "property_id": property_id,
        "list_date": "2026-08-01",
    }


def test_compile_keeps_active_wheaton():
    config = {
        "wheaton_for_sale": {
            "cities": ["wheaton"],
            "zips": ["60187", "60189"],
            "radius_miles": 3,
        },
        "towns": {
            "Wheaton": {
                "search_location": "Wheaton, IL",
                "cities": ["wheaton"],
                "zips": ["60187", "60189"],
                "radius_miles": 3,
                "county": "DuPage",
            }
        },
        "scan": {"radius_miles": 3},
    }
    records, stats = compile_wheaton_listings([_raw()], config=config)
    assert stats.get("final_count", 0) >= 1
    assert records
    assert records[0]["nearest_target"] == "Wheaton"
    assert records[0]["is_wheaton_listing"] is True


def test_compile_rejects_inactive_and_out_of_town():
    config = {
        "wheaton_for_sale": {
            "cities": ["wheaton"],
            "zips": ["60187", "60189"],
            "radius_miles": 3,
        },
        "towns": {
            "Wheaton": {
                "search_location": "Wheaton, IL",
                "cities": ["wheaton"],
                "zips": ["60187", "60189"],
                "radius_miles": 3,
                "county": "DuPage",
            }
        },
        "scan": {"radius_miles": 3},
    }
    pending = _raw(status="pending", property_id="pending-1")
    pending["flags"] = {"is_pending": True}
    other = _raw(
        city="Naperville",
        zip_code="60540",
        lat=41.7508,
        lon=-88.1535,
        property_id="nap-1",
        address="1 Downtown St",
    )
    good = _raw(property_id="good-1", zip_code="60189")
    records, stats = compile_wheaton_listings([pending, other, good], config=config)
    assert stats.get("rejected_inactive", 0) >= 1
    assert stats.get("rejected_out_of_wheaton", 0) >= 1
    assert any(r.get("property_id") == "good-1" for r in records)
