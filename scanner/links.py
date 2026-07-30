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


def landwatch_search_url(record: dict[str, Any]) -> str:
    """LandWatch often lists acreage not shown on housing sites."""
    city = str(record.get("city") or record.get("nearest_target") or "").strip()
    state = str(record.get("state") or "IL").strip()
    acres = record.get("acres")
    q = f"{city} {state} land for sale"
    if acres:
        q += f" {acres} acres"
    else:
        q += " 20+ acres"
    return f"https://www.landwatch.com/search?q={quote_plus(q)}"


def lands_of_america_search_url(record: dict[str, Any]) -> str:
    city = str(record.get("city") or record.get("nearest_target") or "").strip()
    state = str(record.get("state") or "IL").strip()
    q = f"{city}, {state}"
    return (
        "https://www.landsofamerica.com/search/"
        f"?q={quote_plus(q)}&filters=propertyType:land,farm"
    )


def zillow_land_search_url(record: dict[str, Any]) -> str:
    """Zillow land/lot search near the listing address (manual cross-check)."""
    q = _full_address(record)
    return f"https://www.zillow.com/homes/{quote_plus(q)}_rb/"


def google_land_search_url(record: dict[str, Any]) -> str:
    acres = record.get("acres")
    acre_bit = f"{acres} acres " if acres else "20+ acres "
    q = f"{_full_address(record)} {acre_bit}land for sale"
    return f"https://www.google.com/search?q={quote_plus(q)}"


def attach_alt_links(record: dict[str, Any]) -> dict[str, Any]:
    """Mutate/return record with alt open URLs."""
    record["google_url"] = google_listing_search_url(record)
    record["zillow_url"] = zillow_search_url(record)
    record["redfin_url"] = redfin_search_url(record)
    return record


def attach_land_alt_links(record: dict[str, Any]) -> dict[str, Any]:
    """Housing + land-specialty open URLs for large-tract listings."""
    attach_alt_links(record)
    record["google_url"] = google_land_search_url(record)
    record["zillow_url"] = zillow_land_search_url(record)
    record["landwatch_url"] = landwatch_search_url(record)
    record["lands_of_america_url"] = lands_of_america_search_url(record)
    return record
