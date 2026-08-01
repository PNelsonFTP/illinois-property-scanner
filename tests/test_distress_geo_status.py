"""Unit tests for backlog items: LH classify, acreage, distress gates, status, dedup."""

from __future__ import annotations

from scanner.dedup import deduplicate, normalize_addr
from scanner.distress import (
    detect_distress_signals,
    estimate_acres,
    meets_publish_composite,
)
from scanner.geo import classify_town, is_lake_holiday_area
from scanner.large_land import extract_acres_with_source
from scanner.status import is_verified_active


def test_lake_holiday_wildwood_not_sheridan():
    rec = {
        "address": "12 Wildwood Dr",
        "city": "Sandwich",
        "state": "IL",
        "zip": "60548",
        "details": [{"text": ["Subdivision: Wildwood"]}],
    }
    assert is_lake_holiday_area(rec, {"subdivision": "Wildwood"})
    town, _ = classify_town(rec, {"_include_optional": True, "scan": {"include_optional_towns": True}})
    assert town == "Lake Holiday"


def test_acreage_point58_not_58():
    raw = {
        "description": {"text": "Beautiful .58 Acre lot ready to build.", "type": "land"},
        "location": {"address": {"line": "1 Lot St", "city": "Earlville"}},
    }
    rec = {"lot_size": "", "property_type": "Land", "notes": raw["description"]["text"]}
    acres, source = extract_acres_with_source(raw, rec)
    assert acres is not None
    assert acres < 2, f".58 acre must not become 58 (got {acres} via {source})"


def test_dom_only_fails_publish_composite():
    assert not meets_publish_composite(["high-dom"], score=2, text="nice home")
    assert meets_publish_composite(
        ["high-dom", "price-reduced"], score=4, text="price cut stale listing"
    )
    assert meets_publish_composite(["foreclosure"], score=5, text="bank owned")


def test_small_vacant_lot_rejected_from_distress():
    config = {
        "distress": {"min_land_acres_for_distress": 20, "min_publish_score": 3},
        "scan": {"include_optional_towns": True},
        "_include_optional": True,
    }
    rec = {
        "address": "99 Investor Lot",
        "city": "Earlville",
        "property_type": "Land",
        "list_price": 19900,
        "lot_size": "0.25 acres",
        "notes": "INVESTORS welcome below market vacant lot",
        "dom": 120,
        "_raw_source": "realtor.com",
        "mls_status": "Active",
        "status": "for_sale",
    }
    signals = detect_distress_signals(rec, config)
    acres = signals.get("acres") or estimate_acres(rec)
    assert acres is None or acres < 20
    # Bare investor + below-market on tiny lot should not publish as strong composite
    # (below-market land only when acres >= threshold)
    assert "below-market" not in signals.get("tags", [])


def test_backup_status_inactive():
    active, reason = is_verified_active(
        {"mls_status": "Take Backup", "status": "for_sale", "flags": {}},
        {},
    )
    assert not active
    assert "backup" in reason or "inactive" in reason


def test_kick_out_status_inactive():
    active, _ = is_verified_active(
        {"mls_status": "Kick Out", "status": "active", "flags": {}},
        {},
    )
    assert not active


def test_dedup_prefers_property_id():
    a = {
        "address": "100 Main St",
        "city": "Oswego",
        "zip": "60543",
        "property_id": "PID-1",
        "list_price": 200000,
        "_raw_source": "realtor.com",
        "listing_source": "Realtor.com",
    }
    b = {
        "address": "100 Main Street",
        "city": "Oswego",
        "zip": "60543",
        "property_id": "PID-1",
        "list_price": 195000,
        "_raw_source": "realtor.com",
        "listing_source": "Realtor.com",
    }
    merged = deduplicate([a, b])
    assert len(merged) == 1
    assert merged[0]["property_id"] == "PID-1"


def test_normalize_addr_stable():
    assert normalize_addr("100 Main Street", "Oswego", "60543") == normalize_addr(
        "100 MAIN ST", "OSWEGO", "60543"
    )


def test_within_town_radius_allows_wildwood_without_listing_coords():
    from scanner.config import load_config
    from scanner.geo import within_town_radius

    config = load_config()
    config["_include_optional"] = True
    config.setdefault("scan", {})["include_optional_towns"] = True
    rec = {
        "address": "12 Wildwood Dr",
        "city": "Sandwich",
        "state": "IL",
        "zip": "60548",
        "details": [{"text": ["Subdivision: Wildwood"]}],
    }
    town, _ = classify_town(rec, config)
    assert town == "Lake Holiday"
    # No listing lat/lon — city_center fallback must not reject LH-classified rows.
    assert within_town_radius(rec, town, config) is True
