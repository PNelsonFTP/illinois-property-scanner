"""Coming-soon listings — quarantined stream, not merged into active for-sale modes.

HomeHarvest has no ``coming_soon`` listing_type. Realtor.com hides these from
a plain ``for_sale`` search, so we fetch with ``is_coming_soon: true`` and keep
rows whose flags / status / coming_soon_date indicate coming soon.
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
from scanner.fetch import fetch_town_listings, _merge_unique
from scanner.geo import classify_town, enabled_towns, within_town_radius
from scanner.links import attach_alt_links
from scanner.normalize import normalize_realtor_record
from scanner.status import normalize_status

log = logging.getLogger(__name__)

COMING_SOON_PATH = PROJECT_ROOT / "data" / "coming_soon.json"

_SOLD_OR_PENDING = {
    "sold",
    "closed",
    "pending",
    "contingent",
    "under contract",
    "active under contract",
    "active contingent",
    "off market",
    "off-market",
    "off_market",
    "expired",
    "withdrawn",
    "cancelled",
    "canceled",
    "backup",
    "take backup",
    "kick out",
    "kick-out",
    "kick_out",
}


def is_coming_soon(record: dict[str, Any]) -> bool:
    """True when MLS/status/flags indicate coming soon (not yet active for-sale).

    Mirrors the coming-soon signals used by ``scanner.status.is_verified_active``.
    """
    flags = record.get("flags") or {}
    if flags.get("is_coming_soon"):
        return True
    if record.get("coming_soon_date"):
        return True
    for field in (record.get("mls_status"), record.get("status")):
        normalized = normalize_status(field)
        if not normalized:
            continue
        if normalized in {"coming soon", "coming_soon"} or "coming soon" in normalized:
            return True
    return False


def _is_sold_or_pending(record: dict[str, Any], config: dict | None = None) -> bool:
    flags = record.get("flags") or {}
    if flags.get("is_pending") or flags.get("is_contingent"):
        return True
    inactive = set(_SOLD_OR_PENDING)
    if config:
        inactive.update(normalize_status(s) for s in config.get("inactive_statuses", []))
    inactive.discard("coming soon")
    for field in (record.get("mls_status"), record.get("status")):
        normalized = normalize_status(field)
        if normalized and normalized in inactive:
            return True
    return False


def fetch_coming_soon(
    config: dict,
    *,
    include_optional: bool | None = None,
    towns_filter: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch candidate inventory and keep coming-soon rows only.

    HomeHarvest listing types: for_sale, for_rent, sold, pending, off_market,
    new_community, other, ready_to_build — no dedicated coming_soon type.
    Realtor.com hides coming-soon from a plain for_sale search, so the primary
    pass injects ``is_coming_soon: true``.
    """
    scan_cfg = config.get("scan", {})
    default_radius = scan_cfg.get("radius_miles", 3)
    rural_radius = scan_cfg.get("rural_radius_miles", 6)

    towns = enabled_towns(config, include_optional=include_optional)
    if towns_filter:
        wanted = {t.lower() for t in towns_filter}
        towns = {k: v for k, v in towns.items() if k.lower() in wanted}

    all_records: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _keep(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        kept = [r for r in batch if is_coming_soon(r)]
        for record in kept:
            record["_coming_soon_fetch"] = True
        return kept

    for town_name, town_cfg in towns.items():
        location = town_cfg["search_location"]
        radius = town_cfg.get("radius_miles") or (
            rural_radius if town_name in (config.get("optional_towns") or {}) else default_radius
        )
        batch = fetch_town_listings(
            town_name,
            location,
            radius=radius,
            exclude_pending=False,
            listing_type="for_sale",
            pass_name="coming-soon",
            coming_soon=True,
        )
        kept = _keep(batch)
        added = _merge_unique(all_records, seen, kept)
        log.info("  %s coming-soon unique added: %d (of %d fetched)", town_name, added, len(batch))

        for zip_code in town_cfg.get("zips") or []:
            zip_batch = fetch_town_listings(
                town_name,
                str(zip_code),
                radius=radius,
                exclude_pending=False,
                listing_type="for_sale",
                pass_name=f"coming-soon-zip-{zip_code}",
                coming_soon=True,
            )
            zip_kept = _keep(zip_batch)
            zip_added = _merge_unique(all_records, seen, zip_kept)
            log.info(
                "  %s coming-soon zip %s unique added: %d (of %d fetched)",
                town_name,
                zip_code,
                zip_added,
                len(zip_batch),
            )

        time.sleep(0.25)

    log.info("Coming-soon raw fetch: %d unique", len(all_records))
    return all_records


def compile_coming_soon(
    raw_records: list[dict[str, Any]],
    *,
    config: dict,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Compile active coming-soon listings in configured towns (geo only)."""
    stats: Counter = Counter()
    accepted: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for raw in raw_records:
        if raw.get("_negative_check"):
            continue

        rec = normalize_realtor_record(raw)
        stats["normalized"] += 1

        # Prefer flags/status from normalized record; fall back to raw.
        if not is_coming_soon(rec) and not is_coming_soon(raw):
            stats["rejected_not_coming_soon"] += 1
            continue

        if _is_sold_or_pending(rec, config) or _is_sold_or_pending(raw, config):
            stats["rejected_sold_or_pending"] += 1
            continue

        town, county = classify_town(rec, config)
        if town is None:
            stats["rejected_out_of_zone"] += 1
            continue

        if not within_town_radius(rec, town, config):
            stats["rejected_outside_radius"] += 1
            continue

        if not (rec.get("address") or "").strip():
            stats["rejected_missing_address"] += 1
            continue

        if county and not rec.get("county"):
            rec["county"] = county

        entry = {
            "address": rec.get("address", ""),
            "city": rec.get("city", ""),
            "state": rec.get("state", "IL"),
            "zip": rec.get("zip", ""),
            "county": rec.get("county", ""),
            "nearest_target": town,
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
            "status": rec.get("mls_status") or rec.get("status") or "Coming Soon",
            "mls_status": rec.get("mls_status", ""),
            "listing_source": rec.get("listing_source") or "Realtor.com",
            "listing_url": rec.get("listing_url") or "",
            "photo_url": rec.get("photo_url"),
            "notes": (rec.get("notes") or "")[:500],
            "property_id": rec.get("property_id"),
            "listing_id": rec.get("listing_id"),
            "verified_at": now,
            "verification_source": "realtor.com-coming-soon",
            "verification_note": "coming soon",
            "is_coming_soon": True,
            "lat": rec.get("lat"),
            "lon": rec.get("lon"),
        }
        attach_alt_links(entry)
        if entry["list_price"] and entry["sqft"] and entry["sqft"] > 0:
            entry["price_per_sqft"] = round(entry["list_price"] / entry["sqft"], 2)

        accepted.append(entry)
        stats["accepted_pre_dedup"] += 1

    deduped = deduplicate(accepted)
    stats["duplicates_merged"] = len(accepted) - len(deduped)

    def sort_key(p: dict[str, Any]) -> tuple:
        return (p.get("list_price") is None, p.get("list_price") or 0, p.get("address") or "")

    deduped.sort(key=sort_key)
    for i, record in enumerate(deduped):
        record["id"] = i + 1

    stats["final_count"] = len(deduped)
    return deduped, dict(stats)


def save_coming_soon(records: list[dict[str, Any]], path: Path | None = None) -> Path:
    out = path or COMING_SOON_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(records),
        "records": records,
    }
    with open(out, "w") as handle:
        json.dump(payload, handle, indent=2, default=str)
    log.info("Saved %d coming-soon listings to %s", len(records), out)
    return out


def load_coming_soon(path: Path | None = None) -> list[dict[str, Any]]:
    source = path or COMING_SOON_PATH
    if not source.exists():
        return []
    with open(source) as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return payload
    return payload.get("records", [])


def print_coming_soon_summary(
    records: list[dict[str, Any]],
    stats: dict[str, int],
) -> None:
    print(f"\n{'=' * 60}")
    print("COMING SOON — quarantined (not merged into active modes)")
    print(f"{'=' * 60}")
    for key, value in sorted(stats.items()):
        print(f"  {key}: {value}")
    by_town = Counter(p["nearest_target"] for p in records)
    print(f"\nBy Town ({len(records)} total):")
    for town, count in by_town.most_common():
        print(f"  {town}: {count}")
    print("\nSample:")
    for p in records[:10]:
        price = f"${p['list_price']:,.0f}" if p.get("list_price") else "TBD"
        print(f"  {p['address']}, {p['city']} — {price} — {p['nearest_target']}")
