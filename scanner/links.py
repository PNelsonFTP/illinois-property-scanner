"""Alternate listing open URLs — Realtor.com often blocks browser deep-links."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus


def _full_address(record: dict[str, Any]) -> str:
    parts = [
        str(record.get("address") or "").strip(),
        str(record.get("city") or record.get("nearest_target") or "").strip(),
        str(record.get("state") or "IL").strip(),
        str(record.get("zip") or "").strip(),
    ]
    return " ".join(p for p in parts if p)


def google_listing_search_url(record: dict[str, Any]) -> str:
    q = f"{_full_address(record)} for sale"
    return f"https://www.google.com/search?q={quote_plus(q)}"


def zillow_search_url(record: dict[str, Any]) -> str:
    q = _full_address(record)
    return f"https://www.zillow.com/homes/{quote_plus(q)}_rb/"


def redfin_search_url(record: dict[str, Any]) -> str:
    q = _full_address(record)
    return f"https://www.redfin.com/stingray/do/location-search?location={quote_plus(q)}"


def attach_alt_links(record: dict[str, Any]) -> dict[str, Any]:
    """Mutate/return record with alt open URLs."""
    record["google_url"] = google_listing_search_url(record)
    record["zillow_url"] = zillow_search_url(record)
    record["redfin_url"] = redfin_search_url(record)
    return record
