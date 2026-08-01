"""Acreage parsing — fractional lots must not inflate to whole acres."""

from __future__ import annotations

from scanner.large_land import extract_acres_with_source


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
