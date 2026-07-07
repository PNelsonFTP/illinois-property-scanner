"""Fetch live property listings via HomeHarvest (Realtor.com)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from homeharvest import scrape_property

from scanner.config import RAW_DIR

log = logging.getLogger(__name__)


def fetch_town_listings(
    town_name: str,
    search_location: str,
    *,
    radius: float | None = 3,
    exclude_pending: bool = True,
    foreclosure: bool = False,
    property_type: str | None = None,
) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {
        "location": search_location,
        "listing_type": "for_sale",
        "return_type": "raw",
        "exclude_pending": exclude_pending,
        "extra_property_data": True,
        "limit": 10000,
    }
    if radius:
        kwargs["radius"] = radius
    if foreclosure:
        kwargs["foreclosure"] = True
    if property_type:
        kwargs["property_type"] = property_type

    log.info("Fetching %s (foreclosure=%s, radius=%s)...", search_location, foreclosure, radius)
    results = scrape_property(**kwargs)
    for r in results:
        r["_fetch_town"] = town_name
        r["_fetch_location"] = search_location
        r["_fetch_foreclosure"] = foreclosure
    log.info("  -> %d listings", len(results))
    return results


def fetch_all_towns(config: dict) -> list[dict[str, Any]]:
    scan_cfg = config.get("scan", {})
    radius = scan_cfg.get("radius_miles", 3)
    exclude_pending = scan_cfg.get("exclude_pending", True)
    include_foreclosure = scan_cfg.get("include_foreclosure_search", True)

    all_records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for town_name, town_cfg in config.get("towns", {}).items():
        location = town_cfg["search_location"]

        batches = [
            fetch_town_listings(town_name, location, radius=radius, exclude_pending=exclude_pending),
        ]
        if include_foreclosure:
            batches.append(
                fetch_town_listings(
                    town_name, location, radius=radius,
                    exclude_pending=exclude_pending, foreclosure=True,
                )
            )

        for batch in batches:
            for record in batch:
                pid = record.get("property_id") or record.get("listing_id") or record.get("href")
                if pid and pid in seen_ids:
                    continue
                if pid:
                    seen_ids.add(str(pid))
                all_records.append(record)

    return all_records


def save_raw(records: list[dict], label: str = "realtor-live") -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = RAW_DIR / f"{label}-{ts}.json"
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(records),
        "records": records,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    log.info("Saved raw data to %s", path)
    return path
