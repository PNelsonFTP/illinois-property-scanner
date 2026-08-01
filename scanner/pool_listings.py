"""Active residential listings with private or community pool access.

No distress or recency filtering applies. Listings must be active, residential,
inside a configured area, and have structured pool evidence from MLS data.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scanner.config import PROJECT_ROOT
from scanner.dedup import deduplicate
from scanner.geo import classify_town, within_town_radius
from scanner.links import attach_alt_links
from scanner.normalize import normalize_realtor_record
from scanner.status import is_verified_active

log = logging.getLogger(__name__)

POOL_LISTINGS_PATH = PROJECT_ROOT / "data" / "pool_listings.json"
RESIDENTIAL_TYPES = {"SFH", "Condo", "Townhome", "Manufactured", "Multi-Family"}

_PRIVATE_POOL_TEXT = re.compile(
    r"\b(private|backyard|heated|indoor|in[- ]?ground|above[- ]?ground) pool\b",
    re.IGNORECASE,
)


def detect_pool_evidence(raw: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Return (pool type, evidence) using structured MLS fields where possible."""
    tags = {str(tag).lower() for tag in (raw.get("tags") or [])}
    private = "swimming_pool" in tags
    community = "community_swimming_pool" in tags
    evidence: list[str] = []

    if private:
        evidence.append("MLS feature: swimming pool")
    if community:
        evidence.append("MLS feature: community swimming pool")

    for detail in raw.get("details") or []:
        if not isinstance(detail, dict):
            continue
        category = str(detail.get("category") or "").strip().lower()
        for value in detail.get("text") or []:
            text = str(value).strip()
            low = text.lower()
            if low.startswith("pool features:"):
                private = True
                evidence.append(text)
            elif low in {"in ground pool", "indoor pool", "above ground pool"}:
                private = True
                evidence.append(text)
            elif (
                category in {
                    "homeowners association",
                    "amenities and community features",
                }
                and "pool" in low
            ):
                community = True
                evidence.append(text)

    description = str((raw.get("description") or {}).get("text") or "")
    match = _PRIVATE_POOL_TEXT.search(description)
    if match:
        private = True
        evidence.append(match.group(0))

    # Keep compact, stable evidence for the dashboard.
    evidence = list(dict.fromkeys(evidence))[:5]
    if private and community:
        return "Private + Community", evidence
    if private:
        return "Private", evidence
    if community:
        return "Community", evidence
    return None, []


def compile_pool_listings(
    raw_records: list[dict[str, Any]],
    *,
    config: dict,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Compile active, in-area residential listings with MLS pool evidence."""
    stats: Counter = Counter()
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

        if not within_town_radius(rec, town, config):
            stats["rejected_outside_radius"] += 1
            continue

        active, reason = is_verified_active(rec, config)
        if not active:
            stats["rejected_inactive"] += 1
            continue

        if rec.get("property_type") not in RESIDENTIAL_TYPES:
            stats["rejected_non_residential"] += 1
            continue

        pool_type, evidence = detect_pool_evidence(raw)
        if not pool_type:
            stats["rejected_no_pool"] += 1
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
            "status": rec.get("mls_status") or rec.get("status") or "Active",
            "mls_status": rec.get("mls_status", ""),
            "listing_source": rec.get("listing_source") or "Realtor.com",
            "listing_url": rec.get("listing_url") or "",
            "photo_url": rec.get("photo_url"),
            "notes": (rec.get("notes") or "")[:750],
            "property_id": rec.get("property_id"),
            "listing_id": rec.get("listing_id"),
            "verified_at": now,
            "last_seen_active_at": now,
            "verification_source": "realtor.com-pool-listings",
            "verification_note": reason,
            "pool_type": pool_type,
            "pool_evidence": evidence,
            "is_pool_listing": True,
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
    rank = {"Private + Community": 0, "Private": 1, "Community": 2}
    deduped.sort(
        key=lambda p: (
            rank.get(p.get("pool_type"), 9),
            p.get("list_price") is None,
            p.get("list_price") or 0,
        )
    )
    for i, record in enumerate(deduped):
        record["id"] = i + 1

    stats["final_count"] = len(deduped)
    return deduped, dict(stats)


def save_pool_listings(
    records: list[dict[str, Any]],
    path: Path | None = None,
) -> Path:
    out = path or POOL_LISTINGS_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(records),
        "records": records,
    }
    with open(out, "w") as handle:
        json.dump(payload, handle, indent=2, default=str)
    log.info("Saved %d pool listings to %s", len(records), out)
    return out


def load_pool_listings(path: Path | None = None) -> list[dict[str, Any]]:
    source = path or POOL_LISTINGS_PATH
    if not source.exists():
        return []
    with open(source) as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return payload
    return payload.get("records", [])


def print_pool_listings_summary(
    records: list[dict[str, Any]],
    stats: dict[str, int],
) -> None:
    print(f"\n{'=' * 60}")
    print("HOMES WITH POOLS — active residential, geo only")
    print(f"{'=' * 60}")
    for key, value in sorted(stats.items()):
        print(f"  {key}: {value}")

    by_town = Counter(p["nearest_target"] for p in records)
    by_pool = Counter(p["pool_type"] for p in records)
    print(f"\nBy Town ({len(records)} total):")
    for town, count in by_town.most_common():
        print(f"  {town}: {count}")
    print("\nPool type:")
    for pool_type, count in by_pool.most_common():
        print(f"  {pool_type}: {count}")
