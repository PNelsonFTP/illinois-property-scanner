"""Dedup by property_id even when address is empty."""

from __future__ import annotations

from scanner.dedup import deduplicate


def test_same_property_id_merges():
    records = [
        {
            "property_id": "999888777",
            "address": "",
            "city": "",
            "list_price": 100000,
            "source": "other",
        },
        {
            "property_id": "999888777",
            "address": "",
            "city": "",
            "beds": 3,
            "source": "realtor.com",
            "_raw_source": "realtor.com",
        },
    ]
    merged = deduplicate(records)
    assert len(merged) == 1
    assert merged[0]["property_id"] == "999888777"
    assert merged[0].get("beds") == 3
    assert merged[0].get("list_price") == 100000
