"""Apartments for rent in Wheaton and Somonauk / Lake Holiday.

Dedicated dashboard mode — all-or-nothing (no town toggles). Searches
``for_rent`` inventory only; Sandwich is excluded unless the listing is
Lake Holiday (Wildwood streets / subdivision).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scanner.config import PROJECT_ROOT
from scanner.dedup import deduplicate
from scanner.fetch import _merge_unique, fetch_town_listings, save_raw
from scanner.geo import extract_coords_with_source, is_lake_holiday_area, within_town_radius
from scanner.links import attach_rent_alt_links
from scanner.normalize import normalize_realtor_record
from scanner.status import is_verified_active_rental

log = logging.getLogger(__name__)

APARTMENTS_PATH = PROJECT_ROOT / "data" / "apartments_rent.json"

AREA_WHEATON = "Wheaton"
AREA_SOMONAUK_LH = "Somonauk / Lake Holiday"

_WHEATON_ZIPS = {"60187", "60189"}
_SOMONAUK_ZIPS = {"60552"}
_LAKE_HOLIDAY_ZIPS = {"60548", "60552"}

APARTMENT_TYPES = {"Apartment", "Condo", "Multi-Family", "Townhome"}
EXCLUDED_TYPES = {"SFH", "Land", "Farm", "Manufactured"}
_APARTMENT_TEXT = re.compile(
    r"\b(apartment|apartments|apt\.?|studio|condo|condominium)\b",
    re.I,
)

_DEFAULT_AREAS: list[dict[str, Any]] = [
    {
        "name": AREA_WHEATON,
        "search_locations": ["Wheaton, IL"],
        "cities": ["wheaton"],
        "zips": ["60187", "60189"],
        "county": "DuPage",
        "town_for_radius": "Wheaton",
    },
    {
        "name": AREA_SOMONAUK_LH,
        "search_locations": ["Somonauk, IL", "Lake Holiday, IL"],
        "cities": ["somonauk", "lake holiday"],
        "zips": ["60552", "60548"],
        "county": "DeKalb",
        "town_for_radius": "Somonauk",
    },
]


def _rent_cfg(config: dict) -> dict[str, Any]:
    cfg = dict(config.get("apartments_for_rent") or {})
    cfg.setdefault("radius_miles", 3)
    cfg.setdefault("label", "Apartments for Rent")
    cfg.setdefault("areas", list(_DEFAULT_AREAS))
    return cfg


def is_apartment_rental(record: dict[str, Any]) -> bool:
    """Keep apartment / condo / multi-family / townhome rentals; drop houses and land."""
    ptype = record.get("property_type") or "Unknown"
    notes = record.get("notes") or ""
    desc = record.get("description") or {}
    raw_type = ""
    if isinstance(desc, dict):
        raw_type = str(desc.get("type") or "")
    text = f"{ptype} {raw_type} {notes}"

    if ptype in EXCLUDED_TYPES:
        return False
    if ptype in APARTMENT_TYPES:
        return True
    if ptype in ("Unknown", ""):
        return bool(_APARTMENT_TEXT.search(text))
    lowered = ptype.lower()
    return any(token in lowered for token in ("apartment", "condo", "multi", "townhome", "duplex"))


def classify_rent_area(record: dict[str, Any]) -> str | None:
    """Assign Wheaton or Somonauk / Lake Holiday. Sandwich stays out unless Lake Holiday."""
    city = (record.get("city") or "").strip().lower()
    zip_code = str(record.get("zip") or "").strip()[:5]

    if zip_code and zip_code in _WHEATON_ZIPS:
        return AREA_WHEATON
    if city == "wheaton":
        if zip_code and zip_code not in _WHEATON_ZIPS:
            return None
        return AREA_WHEATON

    if is_lake_holiday_area(record):
        return AREA_SOMONAUK_LH

    if city == "somonauk" or (zip_code and zip_code in _SOMONAUK_ZIPS and city != "sandwich"):
        return AREA_SOMONAUK_LH

    if zip_code == "60552" and city not in {"sandwich", "sheridan", "plano", "yorkville"}:
        return AREA_SOMONAUK_LH

    return None


def _within_area_radius(record: dict[str, Any], area: str, config: dict) -> bool:
    coord_info = extract_coords_with_source(record)
    if not coord_info or coord_info[2] != "listing":
        return True
    if area == AREA_WHEATON:
        return within_town_radius(record, "Wheaton", config)
    return (
        within_town_radius(record, "Somonauk", config)
        or within_town_radius(record, "Lake Holiday", config)
    )


def fetch_apartments_rent(config: dict) -> list[dict[str, Any]]:
    """Fetch for_rent inventory for Wheaton and Somonauk / Lake Holiday only."""
    rcfg = _rent_cfg(config)
    radius = float(rcfg["radius_miles"])
    all_records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for area in rcfg.get("areas") or _DEFAULT_AREAS:
        area_name = area.get("name") or "rent"
        locations = list(area.get("search_locations") or [])
        if area.get("search_location"):
            locations.insert(0, area["search_location"])
        for location in locations:
            batch = fetch_town_listings(
                area_name,
                str(location),
                radius=radius,
                exclude_pending=False,
                listing_type="for_rent",
                pass_name=f"rent-{area_name}",
            )
            for record in batch:
                record["_rent_source"] = "realtor-city"
                record["_rent_area"] = area_name
            added = _merge_unique(all_records, seen, batch)
            log.info("  %s (%s) unique added: %d", area_name, location, added)
            time.sleep(0.2)

        for zip_code in area.get("zips") or []:
            zip_batch = fetch_town_listings(
                area_name,
                str(zip_code),
                radius=radius,
                exclude_pending=False,
                listing_type="for_rent",
                pass_name=f"rent-zip-{zip_code}",
            )
            for record in zip_batch:
                record["_rent_source"] = "realtor-zip"
                record["_rent_area"] = area_name
            zip_added = _merge_unique(all_records, seen, zip_batch)
            log.info("  %s zip %s unique added: %d", area_name, zip_code, zip_added)
            time.sleep(0.2)

    log.info(
        "Apartments-for-rent fetch complete: %d raw records (r=%.0f mi)",
        len(all_records),
        radius,
    )
    return all_records


def compile_apartments_rent(
    raw_records: list[dict[str, Any]],
    *,
    config: dict,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Compile verified-active apartment rentals in the two configured areas."""
    rcfg = _rent_cfg(config)
    stats: Counter = Counter()
    accepted: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for raw in raw_records:
        if raw.get("_negative_check"):
            continue

        rec = normalize_realtor_record(raw)
        rec["_listing_type_query"] = raw.get("_listing_type_query") or "for_rent"
        stats["normalized"] += 1

        if not is_apartment_rental(rec):
            stats["rejected_not_apartment"] += 1
            continue

        area = classify_rent_area(rec)
        if not area:
            zip_code = str(rec.get("zip") or "").strip()[:5]
            city = (rec.get("city") or "").strip().lower()
            if city == "wheaton" and zip_code and zip_code not in _WHEATON_ZIPS:
                stats["rejected_zip_bleed"] += 1
            elif city == "sandwich":
                stats["rejected_sandwich"] += 1
            else:
                stats["rejected_out_of_area"] += 1
            continue

        if not _within_area_radius(rec, area, config):
            stats["rejected_outside_radius"] += 1
            continue

        if not (rec.get("address") or "").strip():
            stats["rejected_missing_address"] += 1
            continue

        active, reason = is_verified_active_rental(rec, config)
        if not active:
            stats["rejected_inactive"] += 1
            continue

        coord_info = extract_coords_with_source(raw) or extract_coords_with_source(rec)
        county = rec.get("county") or (
            "DuPage" if area == AREA_WHEATON else "DeKalb"
        )
        entry = {
            "address": rec.get("address", ""),
            "city": rec.get("city", ""),
            "state": rec.get("state", "IL"),
            "zip": rec.get("zip", ""),
            "county": county,
            "nearest_target": area,
            "rent_area": area,
            "property_type": rec.get("property_type", "Apartment"),
            "list_price": rec.get("list_price"),
            "original_list_price": rec.get("original_list_price"),
            "price_reductions": rec.get("price_reductions") or 0,
            "total_reduced": rec.get("total_reduced"),
            "price_per_sqft": None,
            "dom": rec.get("dom"),
            "beds": rec.get("beds"),
            "baths": rec.get("baths"),
            "sqft": rec.get("sqft"),
            "lot_size": rec.get("lot_size", ""),
            "year_built": rec.get("year_built"),
            "list_date": rec.get("list_date"),
            "status": rec.get("mls_status") or rec.get("status") or "for_rent",
            "mls_status": rec.get("mls_status", ""),
            "listing_source": rec.get("listing_source") or "Realtor.com",
            "listing_url": rec.get("listing_url") or "",
            "photo_url": rec.get("photo_url"),
            "notes": (rec.get("notes") or "")[:500],
            "property_id": rec.get("property_id"),
            "listing_id": rec.get("listing_id"),
            "lat": rec.get("lat") if rec.get("lat") is not None else (
                coord_info[0] if coord_info else None
            ),
            "lon": rec.get("lon") if rec.get("lon") is not None else (
                coord_info[1] if coord_info else None
            ),
            "verified_at": now,
            "last_seen_active_at": now,
            "verification_source": "realtor.com-apartments-rent",
            "verification_note": reason,
            "listing_type": "for_rent",
            "is_apartment_rental": True,
        }
        attach_rent_alt_links(entry)
        if entry["list_price"] and entry["sqft"] and entry["sqft"] > 0:
            entry["price_per_sqft"] = round(entry["list_price"] / entry["sqft"], 2)

        accepted.append(entry)
        stats["accepted_pre_dedup"] += 1

    deduped = deduplicate(accepted)
    stats["duplicates_merged"] = len(accepted) - len(deduped)

    with_date = [p for p in deduped if p.get("list_date")]
    no_date = [p for p in deduped if not p.get("list_date")]
    with_date.sort(key=lambda p: str(p.get("list_date"))[:10], reverse=True)
    no_date.sort(key=lambda p: (p.get("list_price") is None, p.get("list_price") or 0))
    deduped = with_date + no_date
    for i, record in enumerate(deduped):
        record["id"] = i + 1

    out = dict(stats)
    out["final_count"] = len(deduped)
    out["label"] = rcfg.get("label", "Apartments for Rent")
    out["radius_miles"] = rcfg["radius_miles"]
    return deduped, out


def save_apartments_rent(
    records: list[dict[str, Any]],
    path: Path | None = None,
    *,
    config: dict | None = None,
) -> Path:
    out = path or APARTMENTS_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    rcfg = _rent_cfg(config or {})
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(records),
        "label": rcfg.get("label", "Apartments for Rent"),
        "radius_miles": rcfg["radius_miles"],
        "areas": [AREA_WHEATON, AREA_SOMONAUK_LH],
        "records": records,
    }
    with open(out, "w") as handle:
        json.dump(payload, handle, indent=2, default=str)
    log.info("Saved %d apartment rentals to %s", len(records), out)
    return out


def load_apartments_rent(path: Path | None = None) -> list[dict[str, Any]]:
    source = path or APARTMENTS_PATH
    if not source.exists():
        return []
    with open(source) as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return payload
    return payload.get("records", [])


def print_apartments_rent_summary(
    records: list[dict[str, Any]],
    stats: dict[str, Any],
) -> None:
    print(f"\n{'=' * 60}")
    print("APARTMENTS FOR RENT — Wheaton + Somonauk / Lake Holiday")
    print(f"{'=' * 60}")
    for key, value in sorted(stats.items()):
        print(f"  {key}: {value}")

    by_area = Counter(p.get("nearest_target") for p in records)
    print(f"\nBy area ({len(records)} total):")
    for area, count in by_area.most_common():
        print(f"  {area}: {count}")

    by_type = Counter(p.get("property_type") for p in records)
    print("\nBy type:")
    for ptype, count in by_type.most_common():
        print(f"  {ptype}: {count}")

    print("\nNewest 8:")
    for p in records[:8]:
        price = f"${p['list_price']:,.0f}/mo" if p.get("list_price") else "TBD"
        ld = str(p.get("list_date") or "?")[:10]
        print(
            f"  {p.get('address')} — {price} — {p.get('nearest_target')} — "
            f"listed {ld} — {p.get('property_type')}"
        )


def run_apartments_rent_fetch_and_save(config: dict) -> list[dict[str, Any]]:
    raw = fetch_apartments_rent(config)
    save_raw(raw, label="apartments-rent")
    return raw
