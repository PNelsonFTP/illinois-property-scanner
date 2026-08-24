"""Normalize raw listing records into a common schema."""

from __future__ import annotations

import re
from typing import Any

from scanner.distress import extract_county, extract_dom_from_details, extract_original_price


def _photo_url(record: dict[str, Any]) -> str | None:
    photos = record.get("photos") or record.get("photo") or []
    if isinstance(photos, list) and photos:
        p = photos[0]
        if isinstance(p, dict):
            return p.get("href") or p.get("url")
        return str(p)
    return record.get("photo_url")


def _address_parts(record: dict[str, Any]) -> dict[str, str]:
    loc = record.get("location") or {}
    addr = loc.get("address") or {}
    if isinstance(record.get("address"), str) and record["address"]:
        return {
            "line": record["address"],
            "city": record.get("city") or "",
            "state": record.get("state") or "IL",
            "zip": record.get("zip") or "",
        }
    return {
        "line": addr.get("line") or record.get("address") or "",
        "city": addr.get("city") or record.get("city") or "",
        "state": addr.get("state_code") or record.get("state") or "IL",
        "zip": addr.get("postal_code") or record.get("zip") or "",
    }


def _coords(record: dict[str, Any]) -> tuple[float | None, float | None]:
    """Extract lat/lon from raw location.address.coordinate when present."""
    loc = record.get("location") or {}
    addr = loc.get("address") if isinstance(loc, dict) else {}
    if isinstance(addr, dict):
        coord = addr.get("coordinate")
        if isinstance(coord, dict):
            lat, lon = coord.get("lat"), coord.get("lon")
            if lat is not None and lon is not None:
                try:
                    return float(lat), float(lon)
                except (TypeError, ValueError):
                    pass
    if record.get("lat") is not None and record.get("lon") is not None:
        try:
            return float(record["lat"]), float(record["lon"])
        except (TypeError, ValueError):
            pass
    return None, None


def _property_type(record: dict[str, Any]) -> str:
    desc = record.get("description") or {}
    raw = (
        desc.get("type")
        or record.get("property_type")
        or "unknown"
    )
    raw = str(raw).lower()

    mapping = {
        "single_family": "SFH",
        "single-family": "SFH",
        "single family": "SFH",
        "single family residence": "SFH",
        "house": "SFH",
        "apartment": "Apartment",
        "apartments": "Apartment",
        "condo": "Condo",
        "condos": "Condo",
        "townhomes": "Townhome",
        "townhome": "Townhome",
        "townhouse": "Townhome",
        "multi_family": "Multi-Family",
        "duplex": "Multi-Family",
        "land": "Land",
        "lot": "Land",
        "vacant land": "Land",
        "farm": "Farm",
        "farms": "Farm",
        "mobile": "Manufactured",
        "manufactured": "Manufactured",
        "mobile home": "Manufactured",
        "mobile/manufactured home": "Manufactured",
    }
    for key, val in mapping.items():
        if key in raw:
            return val
    if "mobile" in raw or "manufactured" in raw:
        return "Manufactured"
    if raw in ("unknown", ""):
        return "Unknown"
    return raw.replace("_", " ").title()


def normalize_realtor_record(record: dict[str, Any]) -> dict[str, Any]:
    """Convert a HomeHarvest/Realtor.com raw record to standard internal format."""
    addr = _address_parts(record)
    desc = record.get("description") or {}
    dom = extract_dom_from_details(record.get("details"))
    orig = extract_original_price(record.get("details"))
    list_price = record.get("list_price")
    county = extract_county(record.get("details")) or ""

    baths = desc.get("baths") or desc.get("baths_consolidated")
    if baths is None:
        full = desc.get("baths_full") or 0
        half = desc.get("baths_half") or 0
        if full or half:
            baths = float(full) + 0.5 * float(half)

    lot_sqft = desc.get("lot_sqft")
    lot_size = record.get("lot_size") or (f"{lot_sqft:,} sq ft" if lot_sqft else "")

    price_cuts = 0
    total_reduced = None
    if orig and list_price and orig > list_price:
        price_cuts = 1
        total_reduced = orig - list_price

    href = record.get("href") or record.get("url") or record.get("listing_url") or ""
    lat, lon = _coords(record)

    return {
        "address": addr["line"],
        "city": addr["city"],
        "state": addr["state"],
        "zip": addr["zip"],
        "county": county,
        "property_type": _property_type(record),
        "list_price": list_price,
        "original_list_price": orig,
        "price_cuts": price_cuts,
        "price_reductions": price_cuts,
        "total_reduced": total_reduced,
        "dom": dom,
        "beds": desc.get("beds"),
        "baths": baths,
        "sqft": desc.get("sqft"),
        "lot_size": lot_size,
        "year_built": desc.get("year_built"),
        "status": record.get("status") or "",
        "mls_status": record.get("mls_status") or "",
        "flags": record.get("flags") or {},
        "listing_source": "Realtor.com",
        "source": "Realtor.com",
        "url": href,
        "listing_url": href,
        "photo_url": _photo_url(record),
        "notes": (desc.get("text") or "")[:2000],
        "details": record.get("details"),
        "description": desc,
        "property_id": record.get("property_id"),
        "listing_id": record.get("listing_id"),
        "list_date": record.get("list_date"),
        "last_update_date": record.get("last_update_date"),
        "lat": lat,
        "lon": lon,
        "_fetch_town": record.get("_fetch_town"),
        "_raw_source": "realtor.com",
    }


def normalize_legacy_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize old v2-*.json hand-curated records."""
    out = dict(record)
    out.setdefault("state", "IL")
    out["source"] = record.get("source") or record.get("listing_source") or "legacy"
    out["listing_source"] = out["source"]
    out["url"] = record.get("url") or record.get("listing_url") or ""
    out["listing_url"] = out["url"]
    out["price_cuts"] = record.get("price_cuts", record.get("price_reductions", 0))
    out["price_reductions"] = out["price_cuts"]
    out["_raw_source"] = "legacy"
    return out
