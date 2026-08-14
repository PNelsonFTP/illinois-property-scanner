#!/usr/bin/env python3
"""Parallel town-group fetch, then single-process compile for all dashboard modes.

Pipeline:
  1) Parallel distress discovery (optional towns on; optional --enable-counties)
  2) Single-process distressed compile + full reverify + URL checks
  3) Homes-with-pools compile from that inventory
  4) Dedicated large-land fetch/compile (20+ ac / 40 mi Lake Holiday)
  5) Dedicated caves/bunkers fetch/compile (near ZIP 60189)
  6) Dedicated Wheaton for-sale fetch/compile (all active)
  7) Parallel new-listings (7d) fetch/compile
  8) Rebuild markdown + multi-mode dashboard

Speed comes from concurrent discovery. Accuracy comes from one merged compile
and reverify before publish. See docs/OPERATIONS.md and docs/PUBLISHING.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner.audit import (  # noqa: E402
    annotate_staleness,
    archive_compiled_snapshot,
    detect_changes,
    load_previous_compiled,
    save_change_report,
    write_rejection_audit,
)
from scanner.compile import compile_records, print_summary, save_compiled  # noqa: E402
from scanner.config import PROJECT_ROOT, ensure_dirs, load_config  # noqa: E402
from scanner.fetch import (  # noqa: E402
    _merge_unique,
    _record_key,
    fetch_all_towns,
    get_fetch_health,
    is_fetch_catastrophic,
    save_raw,
)
from scanner.new_listings import (  # noqa: E402
    compile_new_listings,
    fetch_new_listings,
    print_new_listings_summary,
    save_new_listings,
)
from scanner.caves import (  # noqa: E402
    compile_caves_listings,
    fetch_caves_listings,
    print_caves_summary,
    save_caves_listings,
)
from scanner.wheaton_listings import (  # noqa: E402
    compile_wheaton_listings,
    fetch_wheaton_listings,
    print_wheaton_summary,
    save_wheaton_listings,
)
from scanner.large_land import (  # noqa: E402
    compile_large_land,
    fetch_large_land,
    print_large_land_summary,
    save_large_land,
)
from scanner.pool_listings import (  # noqa: E402
    compile_pool_listings,
    fetch_pool_listings,
    print_pool_listings_summary,
    save_pool_listings,
)
from scanner.coming_soon import (  # noqa: E402
    compile_coming_soon,
    fetch_coming_soon,
    print_coming_soon_summary,
    save_coming_soon,
)
from scanner.verify import reverify_properties  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("parallel_refresh")

# Town groups chosen to balance API load vs wall-clock time
TOWN_GROUPS = [
    ["Wheaton", "Oswego"],
    ["Sandwich", "Somonauk", "Lake Holiday"],
    ["Leland", "Earlville", "Waterman", "Sheridan"],
    ["Yorkville", "Plano", "Hinckley"],
]


def _fetch_group(config: dict, towns: list[str], *, new_listings: bool, days: int) -> list[dict]:
    label = ",".join(towns)
    log.info("Worker start: %s (%s)", label, "new-listings" if new_listings else "distress")
    if new_listings:
        records = fetch_new_listings(
            config,
            days=days,
            include_optional=True,
            towns_filter=towns,
        )
    else:
        records = fetch_all_towns(
            config,
            include_optional=True,
            towns_filter=towns,
        )
    log.info("Worker done: %s → %d raw records", label, len(records))
    return records


def _merge(batches: list[list[dict]]) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for batch in batches:
        _merge_unique(merged, seen, batch)
    return merged


def _rebuild(scan_date: str, scan_time: str) -> None:
    import os
    import subprocess

    env = {**os.environ, "SCAN_DATE": scan_date, "SCAN_TIME": scan_time}
    for script_name in ("build_markdown.py", "build_dashboard.py"):
        script = PROJECT_ROOT / script_name
        log.info("Running %s...", script_name)
        subprocess.run(
            [sys.executable, str(script)],
            check=True,
            cwd=PROJECT_ROOT,
            env=env,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Parallel full refresh")
    parser.add_argument("--workers", type=int, default=3, help="Parallel town-group workers")
    parser.add_argument("--new-days", type=int, default=7)
    parser.add_argument("--skip-new-listings", action="store_true")
    parser.add_argument("--skip-large-land", action="store_true")
    parser.add_argument("--skip-pool-listings", action="store_true")
    parser.add_argument("--skip-caves", action="store_true")
    parser.add_argument("--skip-wheaton", action="store_true")
    parser.add_argument("--skip-coming-soon", action="store_true")
    parser.add_argument("--no-markdown", action="store_true")
    parser.add_argument(
        "--enable-counties",
        action="store_true",
        help="Also run county-wide for_sale sweeps (slower, more coverage)",
    )
    parser.add_argument(
        "--include-public-records",
        action="store_true",
        help="Merge data/public_records/*.csv into distress compile",
    )
    args = parser.parse_args()

    ensure_dirs()
    config = load_config()
    scan_cfg = config.setdefault("scan", {})
    scan_cfg["include_optional_towns"] = True
    config["_include_optional"] = True
    if args.enable_counties:
        scan_cfg["include_county_searches"] = True
        log.info("County sweeps ENABLED for this run")

    now = datetime.now(ZoneInfo("America/Chicago"))
    scan_date, scan_time = now.strftime("%B %d, %Y"), now.strftime("%-I:%M %p %Z")
    workers = max(1, min(args.workers, len(TOWN_GROUPS)))

    # --- Parallel distress discovery ---
    log.info("Parallel distress fetch: %d groups, %d workers", len(TOWN_GROUPS), workers)
    distress_batches: list[list[dict]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_group, config, group, new_listings=False, days=args.new_days): group
            for group in TOWN_GROUPS
        }
        for fut in as_completed(futures):
            group = futures[fut]
            try:
                distress_batches.append(fut.result())
            except Exception as exc:
                log.error("Distress worker failed for %s: %s", group, exc)
                raise

    live_records = _merge(distress_batches)
    raw_path = save_raw(live_records, label="realtor-live-parallel")
    log.info("Merged distress raw: %d unique → %s", len(live_records), raw_path)
    health = get_fetch_health()
    log.info(
        "Fetch health (last worker): calls=%d ok=%d empty=%d failed=%d",
        health["calls"], health["ok"], health["empty"], health["failed"],
    )
    usable = [r for r in live_records if not r.get("_negative_check")]
    if not usable or is_fetch_catastrophic(live_records):
        log.error(
            "Aborting parallel refresh: catastrophic empty fetch (usable=%d)",
            len(usable),
        )
        return 1

    # --- Single-process compile + full reverify (accuracy gate) ---
    previous = load_previous_compiled()
    final, stats, _ = compile_records(
        live_records,
        include_legacy=False,
        include_public_records=bool(args.include_public_records),
        config=config,
    )
    kept, rejected = reverify_properties(
        final,
        raw_records=live_records,
        config=config,
        check_urls=scan_cfg.get("check_listing_urls", True),
        do_reverify=True,
        max_reverify=None,
    )
    write_rejection_audit(rejected, label="reverify")
    stats["reverify_kept"] = len(kept)
    stats["reverify_rejected"] = len(rejected)
    final = annotate_staleness(kept, stale_hours=scan_cfg.get("stale_hours", 48))
    for i, p in enumerate(final):
        p["id"] = i + 1
    stats["final_count"] = len(final)

    changes = detect_changes(final, previous)
    save_change_report(changes)
    archive_compiled_snapshot(final)
    save_compiled(final)

    meta = {
        "scan_date": scan_date,
        "scan_time": scan_time,
        "total_properties": len(final),
        "stats": stats,
        "live_fetched": len(live_records),
        "parallel_groups": TOWN_GROUPS,
        "changes": {
            "newly_active": len(changes.get("newly_active") or []),
            "removed": len(changes.get("removed_or_inactive") or []),
            "price_cuts": len(changes.get("price_cuts") or []),
        },
    }
    with open(PROJECT_ROOT / "data" / "last_scan.json", "w") as f:
        json.dump(meta, f, indent=2)

    print_summary(final, stats)
    print(
        f"\nChanges vs prior scan: +{len(changes.get('newly_active') or [])} new, "
        f"-{len(changes.get('removed_or_inactive') or [])} removed, "
        f"{len(changes.get('price_cuts') or [])} price cuts"
    )

    # --- Dedicated pool fetch (not limited to distress inventory) ---
    if not args.skip_pool_listings and scan_cfg.get("include_pool_listings", True):
        log.info("Fetching dedicated homes-with-pools inventory...")
        pool_raw = fetch_pool_listings(config, include_optional=True)
        save_raw(pool_raw, label="pool-listings-parallel")
        pool_records, pool_stats = compile_pool_listings(pool_raw, config=config)
        pool_kept, pool_rejected = reverify_properties(
            pool_records,
            raw_records=pool_raw,
            config=config,
            check_urls=False,
            do_reverify=False,
            max_reverify=None,
        )
        write_rejection_audit(pool_rejected, label="pool-validation")
        pool_stats["validation_kept"] = len(pool_kept)
        pool_stats["validation_rejected"] = len(pool_rejected)
        pool_stats["final_count"] = len(pool_kept)
        for i, record in enumerate(pool_kept):
            record["id"] = i + 1
        save_pool_listings(pool_kept)
        print_pool_listings_summary(pool_kept, pool_stats)
        meta["stats"]["pool_listings"] = len(pool_kept)
        with open(PROJECT_ROOT / "data" / "last_scan.json", "w") as f:
            json.dump(meta, f, indent=2)

    # --- Large land (dedicated county/hub fetch; not from residential inventory) ---
    if not args.skip_large_land and scan_cfg.get("include_large_land", True):
        log.info("Fetching large-land inventory (≥20 acres, 40 mi Lake Holiday)...")
        land_raw = fetch_large_land(config)
        save_raw(land_raw, label="large-land-parallel")
        land_records, land_stats = compile_large_land(land_raw, config=config)
        land_kept, land_rejected = reverify_properties(
            land_records,
            raw_records=land_raw,
            config=config,
            check_urls=False,
            do_reverify=True,
            max_reverify=None,
        )
        write_rejection_audit(land_rejected, label="large-land-validation")
        land_stats["validation_kept"] = len(land_kept)
        land_stats["validation_rejected"] = len(land_rejected)
        land_stats["final_count"] = len(land_kept)
        for i, record in enumerate(land_kept):
            record["id"] = i + 1
        save_large_land(land_kept)
        print_large_land_summary(land_kept, land_stats)
        meta["stats"]["large_land"] = len(land_kept)
        with open(PROJECT_ROOT / "data" / "last_scan.json", "w") as f:
            json.dump(meta, f, indent=2)

    # --- Caves / bunkers (regional hubs; text evidence near ZIP 60189) ---
    if not args.skip_caves and scan_cfg.get("include_caves_listings", True):
        log.info("Fetching caves/bunker inventory (hubs near ZIP 60189)...")
        caves_raw = fetch_caves_listings(config)
        save_raw(caves_raw, label="caves-listings-parallel")
        caves_records, caves_stats = compile_caves_listings(caves_raw, config=config)
        caves_kept, caves_rejected = reverify_properties(
            caves_records,
            raw_records=caves_raw,
            config=config,
            check_urls=False,
            do_reverify=True,
            max_reverify=None,
        )
        write_rejection_audit(caves_rejected, label="caves-validation")
        caves_stats["validation_kept"] = len(caves_kept)
        caves_stats["validation_rejected"] = len(caves_rejected)
        caves_stats["final_count"] = len(caves_kept)
        for i, record in enumerate(caves_kept):
            record["id"] = i + 1
        save_caves_listings(caves_kept, config=config)
        print_caves_summary(caves_kept, caves_stats)
        meta["stats"]["caves_listings"] = len(caves_kept)
        with open(PROJECT_ROOT / "data" / "last_scan.json", "w") as f:
            json.dump(meta, f, indent=2)

    # --- Wheaton for sale (all active listings; live reverify) ---
    if not args.skip_wheaton and scan_cfg.get("include_wheaton_listings", True):
        log.info("Fetching all Wheaton, IL for-sale listings...")
        wheaton_raw = fetch_wheaton_listings(config)
        save_raw(wheaton_raw, label="wheaton-listings-parallel")
        wheaton_records, wheaton_stats = compile_wheaton_listings(
            wheaton_raw, config=config
        )
        wheaton_kept, wheaton_rejected = reverify_properties(
            wheaton_records,
            raw_records=wheaton_raw,
            config=config,
            check_urls=False,
            do_reverify=True,
            max_reverify=None,
        )
        write_rejection_audit(wheaton_rejected, label="wheaton-validation")
        wheaton_stats["validation_kept"] = len(wheaton_kept)
        wheaton_stats["validation_rejected"] = len(wheaton_rejected)
        wheaton_stats["final_count"] = len(wheaton_kept)
        for i, record in enumerate(wheaton_kept):
            record["id"] = i + 1
        save_wheaton_listings(wheaton_kept, config=config)
        print_wheaton_summary(wheaton_kept, wheaton_stats)
        meta["stats"]["wheaton_listings"] = len(wheaton_kept)
        with open(PROJECT_ROOT / "data" / "last_scan.json", "w") as f:
            json.dump(meta, f, indent=2)

    # --- Coming soon (quarantined; not merged into active modes) ---
    if not args.skip_coming_soon and scan_cfg.get("include_coming_soon", True):
        log.info("Fetching coming-soon listings (quarantined stream)...")
        soon_raw = fetch_coming_soon(config, include_optional=True)
        save_raw(soon_raw, label="coming-soon-parallel")
        soon_records, soon_stats = compile_coming_soon(soon_raw, config=config)
        save_coming_soon(soon_records)
        print_coming_soon_summary(soon_records, soon_stats)
        meta["stats"]["coming_soon"] = len(soon_records)
        with open(PROJECT_ROOT / "data" / "last_scan.json", "w") as f:
            json.dump(meta, f, indent=2)

    # --- Parallel new-listings (geo only) ---
    if not args.skip_new_listings:
        log.info("Parallel new-listings fetch (last %d days)...", args.new_days)
        new_batches: list[list[dict]] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_fetch_group, config, group, new_listings=True, days=args.new_days): group
                for group in TOWN_GROUPS
            }
            for fut in as_completed(futures):
                group = futures[fut]
                try:
                    new_batches.append(fut.result())
                except Exception as exc:
                    log.error("New-listings worker failed for %s: %s", group, exc)
                    raise
        new_raw = _merge(new_batches)
        save_raw(new_raw, label=f"new-listings-{args.new_days}d-parallel")
        new_records, new_stats = compile_new_listings(
            new_raw, config=config, days=args.new_days,
        )
        save_new_listings(new_records)
        print_new_listings_summary(new_records, new_stats, days=args.new_days)
        meta["stats"]["new_listings_7d"] = len(new_records)
        with open(PROJECT_ROOT / "data" / "last_scan.json", "w") as f:
            json.dump(meta, f, indent=2)

    if not args.no_markdown and final:
        _rebuild(scan_date, scan_time)
        log.info(
            "Dashboard ready: file://%s",
            PROJECT_ROOT / "dashboard" / "distressed-property-dashboard.html",
        )

    # Quiet unused import warning for _record_key if linters complain — kept for parity
    _ = _record_key
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
