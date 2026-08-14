"""Acreage parsing — fractional lots must not inflate to whole acres."""

from __future__ import annotations

from scanner.config import load_config
from scanner.large_land import compile_large_land, extract_acres_with_source


def test_leading_dot_acre_with_dimensions_under_one():
    raw = {
        "description": {"text": "Beautiful .58 Acre lot ready to build"},
        "details": [
            {
                "text": [
                    "Lot Size Dimensions: 110 X 232.7",
                ]
            }
        ],
    }
    acres, source = extract_acres_with_source(raw, {"lot_size": ".58 Acre"})
    assert acres is not None
    assert acres < 1.0
    assert acres > 0.5
    assert source in {
        "mls_dimensions_feet",
        "text_description",
        "text_lot_conflict_prefer_small",
    }


def test_text_only_dot_fifty_eight_acre():
    raw = {
        "description": {"text": "Nice .58 Acre parcel in town"},
        "details": [],
    }
    acres, source = extract_acres_with_source(raw, None)
    assert acres == 0.58
    assert source == "text_description"


def test_text_acres_without_lot_cue_tagged_untrusted():
    raw = {
        "description": {"text": "Enjoy 25 acres of recreation nearby"},
        "details": [],
    }
    acres, source = extract_acres_with_source(raw, None)
    assert acres == 25.0
    assert source == "text_no_lot_cue"


def test_city_center_within_centroid_compiles():
    """Rural tracts that omit listing coords should still publish inside 30 mi."""
    raw = {
        "description": {"text": "40 acre farm", "type": "farm", "lot_sqft": 40 * 43560},
        "details": [{"text": ["Lot Size Acres: 40"]}],
        "location": {
            "address": {
                "line": "1 Farm Rd",
                "city": "Earlville",
                "state_code": "IL",
                "postal_code": "60518",
            }
        },
        "list_price": 400000,
        "status": "for_sale",
        "mls_status": "Active",
        "flags": {},
        "property_id": "land-cc-1",
    }
    records, stats = compile_large_land([raw], config=load_config())
    assert stats.get("rejected_city_center_coords", 0) == 0
    assert any(r.get("property_id") == "land-cc-1" for r in records)
