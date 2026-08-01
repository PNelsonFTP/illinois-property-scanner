"""Distress publish composite, bare investor, and land acre gates."""

from __future__ import annotations

from scanner.distress import detect_distress_signals, meets_publish_composite


def test_dom_only_fails_publish_composite():
    assert meets_publish_composite(["high-dom"], score=2, text="") is False


def test_high_dom_plus_price_reduced_passes():
    assert (
        meets_publish_composite(["high-dom", "price-reduced"], score=2, text="")
        is True
    )


def test_bare_investor_gets_no_tag():
    result = detect_distress_signals(
        {
            "notes": "Great opportunity for investors looking to build",
            "property_type": "Land",
            "list_price": 20000,
            "lot_size": "0.25 acres",
            "dom": 40,
        }
    )
    tags = {t.lower() for t in result["tags"]}
    assert "investor" not in tags
    assert "investor-special" not in tags


def test_land_under_20ac_no_below_market():
    result = detect_distress_signals(
        {
            "notes": "Vacant lot",
            "property_type": "Land",
            "list_price": 18000,
            "lot_size": "0.3 acres",
            "dom": 200,
        }
    )
    tags = {t.lower() for t in result["tags"]}
    assert "below-market" not in tags
    assert result.get("acres") is not None
    assert result["acres"] < 20
