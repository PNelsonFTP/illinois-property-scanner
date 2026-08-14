"""All active for-sale listings in Wheaton, IL (no distress / age filters).

Dedicated dashboard mode — all-or-nothing (no town toggles). Verifies active
status via MLS fields plus sold/pending negative checks and a live reverify.
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scanner.config import PROJECT_ROOT
from scanner.dedup import deduplicate
from scanner.fetch import _merge_unique, fetch_town_listings, save_raw
from scanner.geo import extract_coords_with_source, within_town_radius
from scanner.links import attach_alt_links
from scanner.normalize import normalize_realtor_record
from scanner.status import is_verified_active

log = logging.getLogger(__name__)

WHEATON_PATH = PROJECT_ROOT / "data" / "wheaton_listings.json"

_DEFAULT_ZIPS = ["60187", "60189"]
_DEFAULT_CITIES = {"wheaton"}


def _wheaton_cfg(config: dict) -> dict[str, Any]:
    cfg = dict(config.get("wheaton_for_sale") or {})
    town = (config.get("towns") or {}).get("Wheaton") or {}
    cfg.setdefault("search_location", town.get("search_location") or "Wheaton, IL")
    cfg.setdefault("label", "Wheaton, IL")
    cfg.setdefault("radius_miles", float(town.get("radius_miles") or 3))
    cfg.setdefault("zips", list(town.get("zips") or _DEFAULT_ZIPS))
    cfg.setdefault("cities", list(town.get("cities") or ["wheaton"]))
    return cfg


def _is_wheaton_listing(rec: dict[str, Any], cfg: dict[str, Any]) -> bool:
    city = (rec.get("city") or "").strip().lower()
    zip_code = str(rec.get("zip") or "").strip()[:5]
    allowed_cities = {c.strip().lower() for c in cfg.get("cities") or _DEFAULT_CITIES}
    allowed_zips = {str(z).strip()[:5] for z in cfg.get("zips") or _DEFAULT_ZIPS}
    if city in allowed_cities:
        return True
    if zip_code and zip_code in allowed_zips:
        return True
    return False


def fetch_wheaton_listings(config: dict) -> list[dict[str, Any]]:
    """Fetch all for_sale inventory for Wheaton + ZIPs, with sold/pending checks."""
    wcfg = _wheaton_cfg(config)
    scan_cfg = config.get("scan") or {}
    verify_cfg = config.get("verification") or {}
    exclude_pending = scan_cfg.get("exclude_pending", True)
    radius = float(wcfg["radius_miles"])
    sold_days = verify_cfg.get("sold_lookback_days", 90)
    pending_days = verify_cfg.get("pending_lookback_days", 30)

    all_records: list[dict[str, Any]] = []
    seen: set[str] = set()

    location = wcfg["search_location"]
    batch = fetch_town_listings(
        "Wheaton",
        location,
        radius=radius,
        exclude_pending=exclude_pending,
        listing_type="for_sale",
        pass_name="wheaton-all-for-sale",
    )
    for record in batch:
        record["_wheaton_source"] = "realtor-city"
    added = _merge_unique(all_records, seen, batch)
    log.info("  Wheaton city unique added: %d", added)

    for zip_code in wcfg.get("zips") or []:
        zip_batch = fetch_town_listings(
            "Wheaton",
            str(zip_code),
            radius=radius,
            exclude_pending=exclude_pending,
            listing_type="for_sale",
            pass_name=f"wheaton-zip-{zip_code}",
        )
        for record in zip_batch:
            record["_wheaton_source"] = "realtor-zip"
        zip_added = _merge_unique(all_records, seen, zip_batch)
        log.info("  Wheaton zip %s unique added: %d", zip_code, zip_added)
        time.sleep(0.2)

    if scan_cfg.get("include_sold_pending_checks", True):
        sold = fetch_town_listings(
            "Wheaton",
            location,
            radius=radius,
            listing_type="sold",
            past_days=sold_days,
            exclude_pending=False,
            pass_name="wheaton-sold",
        )
        for record in sold:
            record["_negative_check"] = "sold"
            record["_wheaton_source"] = "realtor-sold-check"
        _merge_unique(all_records, seen, sold)

        pending = fetch_town_listings(
            "Wheaton",
            location,
            radius=radius,
            listing_type="pending",
            past_days=pending_days,
            exclude_pending=False,
            pass_name="wheaton-pending",
        )
        for record in pending:
            record["_negative_check"] = "pending"
            record["_wheaton_source"] = "realtor-pending-check"
        _merge_unique(all_records, seen, pending)

        for zip_code in (wcfg.get("zips") or [])[:2]:
            sold_z = fetch_town_listings(
                "Wheaton",
                str(zip_code),
                radius=radius,
                listing_type="sold",
                past_days=sold_days,
                exclude_pending=False,
                pass_name=f"wheaton-sold-zip-{zip_code}",
            )
            for record in sold_z:
                record["_negative_check"] = "sold"
                record["_wheaton_source"] = "realtor-sold-check"
            _merge_unique(all_records, seen, sold_z)
            time.sleep(0.15)

    log.info(
        "Wheaton for-sale fetch complete: %d raw records (r=%.0f mi)",
        len(all_records),
        radius,
    )
    return all_records


def compile_wheaton_listings(
    raw_records: list[dict[str, Any]],
    *,
    config: dict,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Compile every verified-active for-sale listing in Wheaton."""
    wcfg = _wheaton_cfg(config)
    stats: Counter = Counter()
    accepted: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for raw in raw_records:
        if raw.get("_negative_check"):
            continue

        rec = normalize_realtor_record(raw)
        stats["normalized"] += 1

        if not _is_wheaton_listing(rec, wcfg):
            stats["rejected_out_of_wheaton"] += 1
            continue

        # ZIP bleed guard: city-label "Wheaton" without listing coords can
        # pull Carol Stream / Glen Ellyn ZIPs. Require a Wheaton ZIP when
        # listing lat/lon are missing; otherwise keep the radius check.
        coord_info = extract_coords_with_source(raw) or extract_coords_with_source(rec)
        has_listing_coords = (
            coord_info is not None and coord_info[2] == "listing"
        )
        if not has_listing_coords:
            zip_code = str(rec.get("zip") or "").strip()[:5]
            allowed_zips = {
                str(z).strip()[:5] for z in (wcfg.get("zips") or _DEFAULT_ZIPS)
            }
            if zip_code not in allowed_zips:
                stats["rejected_zip_bleed"] += 1
                continue
        elif not within_town_radius(rec, "Wheaton", config):
            stats["rejected_outside_radius"] += 1
            continue

        if not (rec.get("address") or "").strip():
            stats["rejected_missing_address"] += 1
            continue

        active, reason = is_verified_active(rec, config)
        if not active:
            stats["rejected_inactive"] += 1
            continue

        entry = {
            "address": rec.get("address", ""),
            "city": rec.get("city", ""),
            "state": rec.get("state", "IL"),
            "zip": rec.get("zip", ""),
            "county": rec.get("county", "") or "DuPage",
            "nearest_target": "Wheaton",
            "property_type": rec.get("property_type", "Unknown"),
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
            "status": rec.get("mls_status") or rec.get("status") or "Active",
            "mls_status": rec.get("mls_status", ""),
            "listing_source": rec.get("listing_source") or "Realtor.com",
            "listing_url": rec.get("listing_url") or "",
            "photo_url": rec.get("photo_url"),
            "notes": (rec.get("notes") or "")[:500],
            "property_id": rec.get("property_id"),
            "listing_id": rec.get("listing_id"),
            "verified_at": now,
            "last_seen_active_at": now,
            "verification_source": "realtor.com-wheaton",
            "verification_note": reason,
            "is_wheaton_listing": True,
        }
        attach_alt_links(entry)
        if entry["list_price"] and entry["sqft"] and entry["sqft"] > 0:
            entry["price_per_sqft"] = round(entry["list_price"] / entry["sqft"], 2)

        accepted.append(entry)
        stats["accepted_pre_dedup"] += 1

    deduped = deduplicate(accepted)
    stats["duplicates_merged"] = len(accepted) - len(deduped)

    # Newest list_date first; undated last by price.
    with_date = [p for p in deduped if p.get("list_date")]
    no_date = [p for p in deduped if not p.get("list_date")]
    with_date.sort(key=lambda p: str(p.get("list_date"))[:10], reverse=True)
    no_date.sort(key=lambda p: (p.get("list_price") is None, p.get("list_price") or 0))
    deduped = with_date + no_date
    for i, record in enumerate(deduped):
        record["id"] = i + 1

    out = dict(stats)
    out["final_count"] = len(deduped)
    out["label"] = wcfg.get("label", "Wheaton, IL")
    out["radius_miles"] = wcfg["radius_miles"]
    return deduped, out


def save_wheaton_listings(
    records: list[dict[str, Any]],
    path: Path | None = None,
    *,
    config: dict | None = None,
) -> Path:
    out = path or WHEATON_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    wcfg = _wheaton_cfg(config or {})
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(records),
        "label": wcfg.get("label", "Wheaton, IL"),
        "search_location": wcfg["search_location"],
        "radius_miles": wcfg["radius_miles"],
        "zips": list(wcfg.get("zips") or []),
        "records": records,
    }
    with open(out, "w") as handle:
        json.dump(payload, handle, indent=2, default=str)
    log.info("Saved %d Wheaton for-sale listings to %s", len(records), out)
    return out


def load_wheaton_listings(path: Path | None = None) -> list[dict[str, Any]]:
    source = path or WHEATON_PATH
    if not source.exists():
        return []
    with open(source) as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return payload
    return payload.get("records", [])


def print_wheaton_summary(
    records: list[dict[str, Any]],
    stats: dict[str, Any],
) -> None:
    print(f"\n{'=' * 60}")
    print("WHEATON FOR SALE — all active listings")
    print(f"{'=' * 60}")
    for key, value in sorted(stats.items()):
        print(f"  {key}: {value}")

    by_type = Counter(p.get("property_type") for p in records)
    print(f"\nBy type ({len(records)} total):")
    for ptype, count in by_type.most_common():
        print(f"  {ptype}: {count}")

    print("\nNewest 8:")
    for p in records[:8]:
        price = f"${p['list_price']:,.0f}" if p.get("list_price") else "TBD"
        ld = str(p.get("list_date") or "?")[:10]
        print(f"  {p.get('address')} — {price} — listed {ld} — {p.get('property_type')}")


def run_wheaton_fetch_and_save(config: dict) -> list[dict[str, Any]]:
    raw = fetch_wheaton_listings(config)
    save_raw(raw, label="wheaton-listings")
    return raw
