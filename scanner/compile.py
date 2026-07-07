"""Compile, filter, score, and write the final property dataset."""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scanner.config import COMPILED_PATH, LEGACY_RAW_GLOB, PROJECT_ROOT, load_config
from scanner.dedup import deduplicate
from scanner.distress import calculate_score, detect_distress_signals
from scanner.normalize import normalize_legacy_record, normalize_realtor_record
from scanner.status import is_active_legacy, is_verified_active

from scanner.geo import classify_town

log = logging.getLogger(__name__)


def load_legacy_raw() -> list[dict[str, Any]]:
    records = []
    for path in sorted(PROJECT_ROOT.glob(LEGACY_RAW_GLOB)):
        if path.name == "v2_compiled.json":
            continue
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    item["_src_file"] = path.name
                records.extend(data)
                log.info("Loaded legacy %s: %d records", path.name, len(data))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Skipping %s: %s", path.name, e)
    return records


def compile_records(
    live_records: list[dict[str, Any]],
    *,
    include_legacy: bool = True,
    config: dict | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    config = config or load_config()
    stats = Counter()

    normalized: list[dict[str, Any]] = []
    for raw in live_records:
        normalized.append(normalize_realtor_record(raw))
        stats["live_normalized"] += 1

    if include_legacy:
        for raw in load_legacy_raw():
            normalized.append(normalize_legacy_record(raw))
            stats["legacy_normalized"] += 1

    accepted: list[dict[str, Any]] = []
    verified_at = datetime.now(timezone.utc).isoformat()

    for rec in normalized:
        town, county = classify_town(rec, config)
        if town is None:
            stats["rejected_out_of_zone"] += 1
            continue

        rec["nearest_target"] = town
        if county and not rec.get("county"):
            rec["county"] = county

        is_live = rec.get("_raw_source") == "realtor.com"
        if is_live:
            active, reason = is_verified_active(rec, config)
            rec["verification_source"] = "realtor.com-live"
        else:
            active, reason = is_active_legacy(rec, config)
            rec["verification_source"] = "legacy-unverified"

        if not active:
            stats["rejected_inactive"] += 1
            log.debug("Rejected inactive: %s — %s", rec.get("address"), reason)
            continue

        distress = detect_distress_signals(rec, config)
        if distress.get("excluded_as_flip"):
            stats["rejected_renovated_flip"] += 1
            continue
        if not distress.get("has_signal"):
            stats["rejected_no_distress"] += 1
            continue

        # Land needs stronger signal than just existing
        ptype = (rec.get("property_type") or "").lower()
        if ptype == "land":
            land_tags = set(distress["tags"])
            if not (land_tags & {"high-dom", "price-reduced", "below-market", "foreclosure", "auction", "motivated"}):
                if not any(k in distress["reasons"] for k in distress["reasons"] if "keyword" in k):
                    stats["rejected_land_no_signal"] += 1
                    continue

        rec["distress_types"] = distress["tags"]
        rec["dom"] = distress.get("dom") or rec.get("dom")
        if distress.get("original_list_price"):
            rec["original_list_price"] = distress["original_list_price"]

        rec["distress_score"] = calculate_score(rec, distress["tags"])
        rec["verified_at"] = verified_at if is_live else rec.get("verified_at")
        rec["status"] = rec.get("mls_status") or rec.get("status") or "Active"
        rec["verification_note"] = reason
        accepted.append(rec)
        stats["accepted_pre_dedup"] += 1

    deduped = deduplicate(accepted)
    stats["duplicates_merged"] = len(accepted) - len(deduped)

    final: list[dict[str, Any]] = []
    for rec in deduped:
        entry = {
            "address": rec.get("address", ""),
            "city": rec.get("city", ""),
            "state": rec.get("state", "IL"),
            "zip": rec.get("zip", ""),
            "county": rec.get("county", ""),
            "nearest_target": rec.get("nearest_target", ""),
            "property_type": rec.get("property_type", "Unknown"),
            "list_price": rec.get("list_price"),
            "original_list_price": rec.get("original_list_price"),
            "price_reductions": rec.get("price_reductions") or rec.get("price_cuts") or 0,
            "total_reduced": rec.get("total_reduced"),
            "price_per_sqft": rec.get("price_per_sqft"),
            "assessed_value": rec.get("assessed_value"),
            "dom": rec.get("dom"),
            "beds": rec.get("beds"),
            "baths": rec.get("baths"),
            "sqft": rec.get("sqft"),
            "lot_size": rec.get("lot_size", ""),
            "year_built": rec.get("year_built"),
            "distress_types": rec.get("distress_types", []),
            "distress_score": rec.get("distress_score", 1),
            "listing_source": rec.get("listing_source") or rec.get("source", ""),
            "listing_url": rec.get("listing_url") or rec.get("url", ""),
            "photo_url": rec.get("photo_url"),
            "status": rec.get("status", ""),
            "mls_status": rec.get("mls_status", ""),
            "verified_at": rec.get("verified_at"),
            "verification_source": rec.get("verification_source", ""),
            "verification_note": rec.get("verification_note", ""),
            "notes": rec.get("notes", ""),
            "all_sources": rec.get("all_sources", []),
            "all_urls": rec.get("all_urls", []),
            "property_id": rec.get("property_id"),
            "listing_id": rec.get("listing_id"),
        }
        if entry["list_price"] and entry["sqft"] and entry["sqft"] > 0:
            entry["price_per_sqft"] = round(entry["list_price"] / entry["sqft"], 2)
        final.append(entry)

    final.sort(key=lambda p: (p["distress_score"], p.get("dom") or 0), reverse=True)
    for i, prop in enumerate(final):
        prop["id"] = i + 1

    stats["final_count"] = len(final)
    return final, dict(stats)


def save_compiled(records: list[dict[str, Any]], path: Path | None = None) -> Path:
    out = path or COMPILED_PATH
    with open(out, "w") as f:
        json.dump(records, f, indent=2, default=str)
    log.info("Saved %d properties to %s", len(records), out)
    return out


def print_summary(records: list[dict[str, Any]], stats: dict[str, int]) -> None:
    print(f"\n{'=' * 60}")
    print(f"COMPILE SUMMARY")
    print(f"{'=' * 60}")
    for key, val in sorted(stats.items()):
        print(f"  {key}: {val}")

    by_town = Counter(p["nearest_target"] for p in records)
    print(f"\nBy Town ({len(records)} total):")
    for town, count in by_town.most_common():
        print(f"  {town}: {count}")

    verified = sum(1 for p in records if p.get("verification_source") == "realtor.com-live")
    print(f"\nLive-verified: {verified}/{len(records)}")

    print(f"\nTop 15 by score:")
    for p in records[:15]:
        price = f"${p['list_price']:,.0f}" if p.get("list_price") else "TBD"
        dom = f"{p['dom']}d" if p.get("dom") else "?"
        tags = ", ".join(p.get("distress_types", [])[:3])
        print(f"  [{p['distress_score']}] {p['address']}, {p['city']} — {price} — DOM:{dom} — {tags}")
