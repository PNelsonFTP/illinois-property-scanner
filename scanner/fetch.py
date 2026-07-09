"""Fetch live property listings — multi-pass, ZIP/county, distress queries."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from homeharvest import scrape_property

from scanner.config import RAW_DIR
from scanner.geo import enabled_towns

log = logging.getLogger(__name__)


def fetch_town_listings(
    town_name: str,
    search_location: str,
    *,
    radius: float | None = 3,
    exclude_pending: bool = True,
    foreclosure: bool = False,
    property_type: str | None = None,
    listing_type: str = "for_sale",
    past_days: int | None = None,
    pass_name: str = "for_sale",
) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {
        "location": search_location,
        "listing_type": listing_type,
        "return_type": "raw",
        "exclude_pending": exclude_pending if listing_type == "for_sale" else False,
        "extra_property_data": True,
        "limit": 10000,
    }
    if radius:
        kwargs["radius"] = radius
    if foreclosure:
        kwargs["foreclosure"] = True
    if property_type:
        kwargs["property_type"] = property_type
    if past_days is not None:
        kwargs["past_days"] = past_days

    log.info(
        "Fetching %s [%s] (type=%s, foreclosure=%s, radius=%s)...",
        search_location, pass_name, listing_type, foreclosure, radius,
    )
    try:
        results = scrape_property(**kwargs)
    except Exception as e:
        log.warning("Fetch failed for %s [%s]: %s", search_location, pass_name, e)
        return []

    for r in results:
        r["_fetch_town"] = town_name
        r["_fetch_location"] = search_location
        r["_fetch_foreclosure"] = foreclosure
        r["_fetch_pass"] = pass_name
        r["_listing_type_query"] = listing_type
    log.info("  -> %d listings", len(results))
    return results


def _record_key(record: dict[str, Any]) -> str | None:
    pid = record.get("property_id") or record.get("listing_id") or record.get("href")
    return str(pid) if pid else None


def _merge_unique(all_records: list, seen: set[str], batch: list) -> int:
    added = 0
    for record in batch:
        key = _record_key(record)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        all_records.append(record)
        added += 1
    return added


def fetch_all_towns(
    config: dict,
    *,
    include_optional: bool | None = None,
    towns_filter: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Multi-pass discovery:
    1. City searches (core + optional)
    2. ZIP searches
    3. County searches (filtered later by geo)
    4. Distress passes (foreclosure, land, mobile)
    5. Sold/pending negative-check inventories (tagged, not published as active)
    """
    scan_cfg = config.get("scan", {})
    default_radius = scan_cfg.get("radius_miles", 3)
    rural_radius = scan_cfg.get("rural_radius_miles", 6)
    exclude_pending = scan_cfg.get("exclude_pending", True)
    include_foreclosure = scan_cfg.get("include_foreclosure_search", True)
    include_zips = scan_cfg.get("include_zip_searches", True)
    include_counties = scan_cfg.get("include_county_searches", True)
    include_distress = scan_cfg.get("include_distress_passes", True)
    include_sold_pending = scan_cfg.get("include_sold_pending_checks", True)

    towns = enabled_towns(config, include_optional=include_optional)
    if towns_filter:
        wanted = {t.lower() for t in towns_filter}
        towns = {k: v for k, v in towns.items() if k.lower() in wanted}

    all_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    verify_cfg = config.get("verification") or {}
    sold_days = verify_cfg.get("sold_lookback_days", 90)
    pending_days = verify_cfg.get("pending_lookback_days", 30)

    for town_name, town_cfg in towns.items():
        location = town_cfg["search_location"]
        radius = town_cfg.get("radius_miles") or (
            rural_radius if town_name in (config.get("optional_towns") or {}) else default_radius
        )

        # Pass 1: standard for_sale
        added = _merge_unique(
            all_records, seen,
            fetch_town_listings(
                town_name, location, radius=radius,
                exclude_pending=exclude_pending, pass_name="for_sale",
            ),
        )
        log.info("  %s for_sale unique added: %d", town_name, added)

        # Pass 2: foreclosure (retry without radius if empty)
        if include_foreclosure:
            fc = fetch_town_listings(
                town_name, location, radius=radius,
                exclude_pending=exclude_pending, foreclosure=True,
                pass_name="foreclosure",
            )
            if not fc:
                fc = fetch_town_listings(
                    town_name, location, radius=None,
                    exclude_pending=exclude_pending, foreclosure=True,
                    pass_name="foreclosure-noradius",
                )
            _merge_unique(all_records, seen, fc)

        # Pass 3: ZIP searches
        if include_zips:
            for zip_code in town_cfg.get("zips") or []:
                _merge_unique(
                    all_records, seen,
                    fetch_town_listings(
                        town_name, str(zip_code), radius=radius,
                        exclude_pending=exclude_pending, pass_name=f"zip-{zip_code}",
                    ),
                )

        # Pass 4: distress property-type passes
        if include_distress:
            for dpass in config.get("distress_passes") or []:
                name = dpass.get("name", "distress")
                if name == "foreclosure":
                    continue  # already done
                if name == "price_reduced":
                    continue  # filtered post-fetch
                ptype = dpass.get("property_type")
                if not ptype:
                    continue
                _merge_unique(
                    all_records, seen,
                    fetch_town_listings(
                        town_name, location, radius=radius,
                        exclude_pending=exclude_pending,
                        property_type=ptype, pass_name=name,
                    ),
                )

        # Pass 5: sold + pending inventories for negative checks
        if include_sold_pending:
            sold = fetch_town_listings(
                town_name, location, radius=radius,
                listing_type="sold", past_days=sold_days,
                exclude_pending=False, pass_name="sold-check",
            )
            for r in sold:
                r["_negative_check"] = "sold"
            _merge_unique(all_records, seen, sold)

            pending = fetch_town_listings(
                town_name, location, radius=radius,
                listing_type="pending", past_days=pending_days,
                exclude_pending=False, pass_name="pending-check",
            )
            for r in pending:
                r["_negative_check"] = "pending"
            _merge_unique(all_records, seen, pending)

        time.sleep(0.3)  # be polite between towns

    # County-level sweeps (for_sale only; geo filter later)
    if include_counties:
        for county in config.get("counties") or []:
            _merge_unique(
                all_records, seen,
                fetch_town_listings(
                    "_county", county, radius=None,
                    exclude_pending=exclude_pending, pass_name=f"county-{county}",
                ),
            )
            time.sleep(0.3)

    log.info("Total unique raw records fetched: %d", len(all_records))
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
