"""Distress publish composite, bare investor, and land acre gates."""

from __future__ import annotations

from scanner.distress import detect_distress_signals, meets_publish_composite


def test_dom_only_fails_publish_composite():
    assert meets_publish_composite(["high-dom"], score=2, text="") is False


def test_high_dom_plus_price_reduced_publishes():
    """Stale listing + any recorded cut is enough (tiny trim still counts)."""
    assert (
        meets_publish_composite(
            ["high-dom", "price-reduced"],
            score=2,
            text="",
            reduction_pct=None,
            price_reductions=1,
        )
        is True
    )
    assert (
        meets_publish_composite(
            ["high-dom", "price-reduced"],
            score=2,
            text="",
            reduction_pct=0.03,
            price_reductions=1,
        )
        is True
    )


def test_tiny_cut_without_high_dom_fails():
    assert (
        meets_publish_composite(
            ["price-reduced"],
            score=2,
            text="",
            reduction_pct=0.03,
            price_reductions=1,
        )
        is False
    )


def test_meaningful_cut_without_high_dom_passes():
    assert (
        meets_publish_composite(
            ["price-reduced"],
            score=2,
            text="",
            reduction_pct=0.12,
            price_reductions=1,
        )
        is True
    )


def test_high_dom_plus_meaningful_price_reduced_passes():
    assert (
        meets_publish_composite(
            ["high-dom", "price-reduced"],
            score=2,
            text="",
            reduction_pct=0.12,
            price_reductions=1,
        )
        is True
    )
    assert (
        meets_publish_composite(
            ["high-dom", "price-reduced"],
            score=2,
            text="",
            reduction_pct=0.04,
            price_reductions=2,
        )
        is True
    )


def test_high_dom_plus_price_reduced_with_strong_tag_passes():
    assert (
        meets_publish_composite(
            ["high-dom", "price-reduced", "as-is"],
            score=2,
            text="",
            reduction_pct=0.03,
            price_reductions=1,
        )
        is True
    )


def test_renovated_flip_high_dom_tiny_cut_excluded():
    result = detect_distress_signals(
        {
            "notes": "Fully renovated and move-in ready turnkey home.",
            "property_type": "single_family",
            "list_price": 290000,
            "original_list_price": 300000,
            "dom": 120,
            "price_reductions": 1,
        }
    )
    assert result.get("excluded_as_flip") is True
    assert result.get("meets_publish_composite") is False
    assert not result.get("tags")


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
