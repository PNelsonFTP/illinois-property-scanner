"""New-to-market listings — all active for-sale in scope, last N days.

No distress filtering. Only geographic distance/town classification applies.
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from scanner.config import PROJECT_ROOT, RAW_DIR
from scanner.dedup import deduplicate
from scanner.fetch import fetch_town_listings, _merge_unique, _record_key
from scanner.geo import classify_town, enabled_towns
from scanner.links import attach_alt_links
from scanner.normalize import normalize_realtor_record
from scanner.status import is_verified_active

log = logging.getLogger(__name__)

NEW_LISTINGS_PATH = PROJECT_ROOT / "data" / "new_listings_7d.json"


def _parse_list_date(value: Any) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _days_on_market_from_list_date(list_date: Any) -> int | None:
    dt = _parse_list_date(list_date)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - dt
    return max(0, int(age.total_seconds() // 86400))


def fetch_new_listings(
    config: dict,
    *,
    days: int = 7,
    include_optional: bool | None = None,
    towns_filter: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch all for_sale listings listed in the last `days` days per town (geo radius only)."""
    scan_cfg = config.get("scan", {})
    default_radius = scan_cfg.get("radius_miles", 3)
    rural_radius = scan_cfg.get("rural_radius_miles", 6)
    exclude_pending = scan_cfg.get("exclude_pending", True)

    towns = enabled_towns(config, include_optional=include_optional)
    if towns_filter:
        wanted = {t.lower() for t in towns_filter}
        towns = {k: v for k, v in towns.items() if k.lower() in wanted}

    all_records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for town_name, town_cfg in towns.items():
        location = town_cfg["search_location"]
        radius = town_cfg.get("radius_miles") or (
            rural_radius if town_name in (config.get("optional_towns") or {}) else default_radius
        )
        batch = fetch_town_listings(
            town_name,
            location,
            radius=radius,
            exclude_pending=exclude_pending,
            listing_type="for_sale",
            past_days=days,
            pass_name=f"new-{days}d",
        )
        added = _merge_unique(all_records, seen, batch)
        log.info("  %s new-%dd unique added: %d", town_name, days, added)
        time.sleep(0.25)

    log.info("New listings raw fetch: %d unique", len(all_records))
    return all_records


def compile_new_listings(
    raw_records: list[dict[str, Any]],
    *,
    config: dict,
    days: int = 7,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """
    Compile new listings with ONLY:
    - in enabled town / radius (classify_town)
    - verified active (not pending/sold)
    - list_date within last `days` (or past_days API result + DOM fallback)

    No distress scoring or distress signal requirements.
    """
    stats: Counter = Counter()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    accepted: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for raw in raw_records:
        if raw.get("_negative_check"):
            continue
        rec = normalize_realtor_record(raw)
        stats["normalized"] += 1

        town, county = classify_town(rec, config)
        if town is None:
            stats["rejected_out_of_zone"] += 1
            continue

        active, reason = is_verified_active(rec, config)
        if not active:
            stats["rejected_inactive"] += 1
            continue

        list_date = rec.get("list_date")
        dt = _parse_list_date(list_date)
        age_days = _days_on_market_from_list_date(list_date)

        # Prefer explicit list_date window; fall back to DOM if present and <= days
        in_window = False
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            in_window = dt >= cutoff
        elif age_days is not None:
            in_window = age_days <= days
        elif raw.get("_fetch_pass", "").startswith("new-"):
            # Came from past_days query — trust API filter
            in_window = True
        else:
            # Unknown date — exclude from "new" view to avoid false positives
            stats["rejected_unknown_date"] += 1
            continue

        if not in_window:
            stats["rejected_older_than_window"] += 1
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
            "dom": rec.get("dom") if rec.get("dom") is not None else age_days,
            "beds": rec.get("beds"),
            "baths": rec.get("baths"),
            "sqft": rec.get("sqft"),
            "lot_size": rec.get("lot_size", ""),
            "year_built": rec.get("year_built"),
            "list_date": list_date,
            "days_since_listed": age_days,
            "status": rec.get("mls_status") or rec.get("status") or "Active",
            "mls_status": rec.get("mls_status", ""),
            "listing_source": rec.get("listing_source") or "Realtor.com",
            "listing_url": rec.get("listing_url") or "",
            "photo_url": rec.get("photo_url"),
            "notes": (rec.get("notes") or "")[:500],
            "property_id": rec.get("property_id"),
            "listing_id": rec.get("listing_id"),
            "verified_at": now,
            "verification_source": "realtor.com-new-listings",
            "verification_note": reason,
            "is_new_listing": True,
            "new_listing_window_days": days,
        }
        attach_alt_links(entry)
        if entry["list_price"] and entry["sqft"] and entry["sqft"] > 0:
            entry["price_per_sqft"] = round(entry["list_price"] / entry["sqft"], 2)

        accepted.append(entry)
        stats["accepted_pre_dedup"] += 1

    deduped = deduplicate(accepted)
    stats["duplicates_merged"] = len(accepted) - len(deduped)

    # Sort newest first
    def sort_key(p):
        dt = _parse_list_date(p.get("list_date"))
        ts = dt.timestamp() if dt else 0
        return (-ts, p.get("list_price") or 0)

    deduped.sort(key=sort_key)
    for i, p in enumerate(deduped):
        p["id"] = i + 1

    stats["final_count"] = len(deduped)
    return deduped, dict(stats)


def save_new_listings(records: list[dict[str, Any]], path: Path | None = None) -> Path:
    out = path or NEW_LISTINGS_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": records[0].get("new_listing_window_days", 7) if records else 7,
        "count": len(records),
        "records": records,
    }
    with open(out, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    log.info("Saved %d new listings to %s", len(records), out)
    return out


def load_new_listings(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or NEW_LISTINGS_PATH
    if not p.exists():
        return []
    with open(p) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("records", [])


def print_new_listings_summary(records: list[dict[str, Any]], stats: dict[str, int], days: int = 7) -> None:
    print(f"\n{'=' * 60}")
    print(f"NEW LISTINGS (last {days} days) — all properties, geo only")
    print(f"{'=' * 60}")
    for key, val in sorted(stats.items()):
        print(f"  {key}: {val}")
    by_town = Counter(p["nearest_target"] for p in records)
    print(f"\nBy Town ({len(records)} total):")
    for town, count in by_town.most_common():
        print(f"  {town}: {count}")
    print(f"\nNewest 10:")
    for p in records[:10]:
        price = f"${p['list_price']:,.0f}" if p.get("list_price") else "TBD"
        ld = (p.get("list_date") or "")[:10]
        print(f"  {p['address']}, {p['city']} — {price} — listed {ld} — {p['nearest_target']}")
