"""Tests for apartments-for-rent compile filters."""

from __future__ import annotations

from scanner.apartments_rent import (
    AREA_SOMONAUK_LH,
    AREA_WHEATON,
    classify_rent_area,
    compile_apartments_rent,
    is_apartment_rental,
)
from scanner.normalize import normalize_realtor_record
from scanner.status import is_verified_active_rental


def _raw(
    *,
    city: str = "Wheaton",
    state: str = "IL",
    zip_code: str = "60187",
    status: str = "for_rent",
    address: str = "100 Main St",
    lat: float = 41.8661,
    lon: float = -88.1070,
    property_id: str = "apt-1",
    prop_type: str = "apartment",
    listing_type: str = "for_rent",
):
    return {
        "description": {"text": "2 bedroom apartment available.", "type": prop_type},
        "location": {
            "address": {
                "line": address,
                "city": city,
                "state_code": state,
                "postal_code": zip_code,
                "coordinate": {"lat": lat, "lon": lon},
            }
        },
        "list_price": 1800,
        "status": status,
        "flags": {},
        "property_id": property_id,
        "list_date": "2026-08-01",
        "_listing_type_query": listing_type,
    }


def _config() -> dict:
    return {
        "apartments_for_rent": {"radius_miles": 3},
        "towns": {
            "Wheaton": {
                "search_location": "Wheaton, IL",
                "cities": ["wheaton"],
                "zips": ["60187", "60189"],
                "radius_miles": 3,
                "county": "DuPage",
            },
            "Somonauk": {
                "search_location": "Somonauk, IL",
                "cities": ["somonauk"],
                "zips": ["60552"],
                "radius_miles": 3,
                "county": "DeKalb",
            },
            "Lake Holiday": {
                "search_location": "Lake Holiday, IL",
                "cities": ["lake holiday"],
                "zips": ["60548", "60552"],
                "radius_miles": 3,
                "county": "LaSalle",
            },
        },
        "scan": {"radius_miles": 3},
    }


def test_keeps_wheaton_apartment():
    records, stats = compile_apartments_rent([_raw()], config=_config())
    assert stats.get("final_count", 0) >= 1
    assert records[0]["nearest_target"] == AREA_WHEATON
    assert records[0]["is_apartment_rental"] is True
    assert records[0]["listing_type"] == "for_rent"
    assert records[0]["property_type"] == "Apartment"


def test_keeps_somonauk_and_lake_holiday():
    somonauk = _raw(
        city="Somonauk",
        zip_code="60552",
        lat=41.6336,
        lon=-88.6812,
        property_id="som-1",
        address="12 Depot St",
    )
    lake = _raw(
        city="Lake Holiday",
        zip_code="60548",
        lat=41.62617,
        lon=-88.69912,
        property_id="lh-1",
        address="100 Holiday Dr",
    )
    wildwood = _raw(
        city="Sandwich",
        zip_code="60548",
        lat=41.62617,
        lon=-88.69912,
        property_id="ww-1",
        address="120 Cardinal Ln Unit A",
    )
    records, stats = compile_apartments_rent(
        [somonauk, lake, wildwood], config=_config()
    )
    ids = {r["property_id"] for r in records}
    assert "som-1" in ids
    assert "lh-1" in ids
    assert "ww-1" in ids
    assert all(r["nearest_target"] == AREA_SOMONAUK_LH for r in records)
    assert stats.get("rejected_sandwich", 0) == 0


def test_rejects_sandwich_that_is_not_lake_holiday():
    sandwich = _raw(
        city="Sandwich",
        zip_code="60548",
        lat=41.6456,
        lon=-88.6217,
        property_id="sand-1",
        address="1 Church St",
    )
    records, stats = compile_apartments_rent([sandwich], config=_config())
    assert not records
    assert stats.get("rejected_sandwich", 0) >= 1


def test_rejects_wheaton_zip_bleed_and_sfh():
    bleed = _raw(city="Wheaton", zip_code="60188", property_id="bleed-60188")
    house = _raw(property_id="sfh-1", prop_type="single_family")
    house["description"]["text"] = "3 bedroom house for rent."
    good = _raw(property_id="good-1", zip_code="60189")
    records, stats = compile_apartments_rent([bleed, house, good], config=_config())
    ids = {r["property_id"] for r in records}
    assert "bleed-60188" not in ids
    assert "sfh-1" not in ids
    assert "good-1" in ids
    assert stats.get("rejected_zip_bleed", 0) >= 1
    assert stats.get("rejected_not_apartment", 0) >= 1


def test_rejects_leased_and_for_sale():
    leased = _raw(status="leased", property_id="leased-1")
    sale = _raw(status="for_sale", property_id="sale-1", listing_type="for_sale")
    sale["_listing_type_query"] = "for_sale"
    good = _raw(property_id="rent-ok")
    records, stats = compile_apartments_rent([leased, sale, good], config=_config())
    ids = {r["property_id"] for r in records}
    assert "leased-1" not in ids
    assert "sale-1" not in ids
    assert "rent-ok" in ids
    assert stats.get("rejected_inactive", 0) >= 2


def test_classify_and_type_helpers():
    wheat = normalize_realtor_record(_raw())
    assert classify_rent_area(wheat) == AREA_WHEATON
    assert is_apartment_rental(wheat) is True

    house = normalize_realtor_record(_raw(prop_type="single_family"))
    house["notes"] = "This bright home features a separate apartment with its own kitchen."
    house["property_type"] = "SFH"
    assert is_apartment_rental(house) is False

    ok, reason = is_verified_active_rental(
        {"status": "for_rent", "mls_status": "active", "_listing_type_query": "for_rent"}
    )
    assert ok is True
    assert "rental" in reason

    bad, _ = is_verified_active_rental({"status": "for_sale", "mls_status": "active"})
    assert bad is False
