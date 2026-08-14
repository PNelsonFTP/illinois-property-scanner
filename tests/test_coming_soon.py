"""Tests for coming-soon compile filters (quarantined stream)."""

from __future__ import annotations

from scanner.coming_soon import compile_coming_soon, is_coming_soon
from scanner.fetch import inject_coming_soon_or_filter


def _raw(
    *,
    city: str = "Wheaton",
    state: str = "IL",
    zip_code: str = "60187",
    status: str = "for_sale",
    mls_status: str = "Coming Soon",
    address: str = "100 Main St",
    lat: float = 41.8661,
    lon: float = -88.1070,
    property_id: str = "cs-1",
    flags: dict | None = None,
):
    return {
        "description": {"text": "Coming soon in Wheaton.", "type": "single_family"},
        "location": {
            "address": {
                "line": address,
                "city": city,
                "state_code": state,
                "postal_code": zip_code,
                "coordinate": {"lat": lat, "lon": lon},
            }
        },
        "list_price": 425000,
        "status": status,
        "mls_status": mls_status,
        "flags": flags if flags is not None else {"is_coming_soon": True},
        "property_id": property_id,
        "list_date": "2026-08-01",
    }


def _config() -> dict:
    return {
        "towns": {
            "Wheaton": {
                "search_location": "Wheaton, IL",
                "cities": ["wheaton"],
                "zips": ["60187", "60189"],
                "radius_miles": 3,
                "county": "DuPage",
            }
        },
        "scan": {"radius_miles": 3, "include_optional_towns": False},
    }


def test_is_coming_soon_flag_and_status():
    assert is_coming_soon(_raw())
    assert is_coming_soon(_raw(flags={}, mls_status="Coming Soon"))
    dated = _raw(flags={}, mls_status="Active")
    dated["coming_soon_date"] = "2026-08-20"
    assert is_coming_soon(dated)
    assert not is_coming_soon(_raw(flags={}, mls_status="Active", status="for_sale"))


def test_inject_coming_soon_or_filter():
    plain = "query { search_location: $search_location status: for_sale }"
    injected = inject_coming_soon_or_filter(plain)
    assert "is_coming_soon: true" in injected
    assert "search_location: $search_location" in injected
    already = "search_location: $search_location is_coming_soon: true"
    assert inject_coming_soon_or_filter(already) == already


def test_compile_keeps_coming_soon_in_wheaton():
    records, stats = compile_coming_soon([_raw()], config=_config())
    assert stats.get("final_count", 0) >= 1
    assert records
    assert records[0]["nearest_target"] == "Wheaton"
    assert records[0]["is_coming_soon"] is True


def test_compile_rejects_sold():
    sold = _raw(property_id="sold-1", status="sold", mls_status="Sold", flags={"is_coming_soon": True})
    good = _raw(property_id="good-1")
    records, stats = compile_coming_soon([sold, good], config=_config())
    assert stats.get("rejected_sold_or_pending", 0) >= 1
    assert any(r.get("property_id") == "good-1" for r in records)
    assert not any(r.get("property_id") == "sold-1" for r in records)


def test_compile_rejects_out_of_zone():
    other = _raw(
        city="Naperville",
        zip_code="60540",
        lat=41.7508,
        lon=-88.1535,
        property_id="nap-1",
        address="1 Downtown St",
    )
    good = _raw(property_id="good-1", zip_code="60189")
    records, stats = compile_coming_soon([other, good], config=_config())
    assert stats.get("rejected_out_of_zone", 0) >= 1
    assert any(r.get("property_id") == "good-1" for r in records)
    assert not any(r.get("property_id") == "nap-1" for r in records)
