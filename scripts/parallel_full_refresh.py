#!/usr/bin/env python3
"""Parallel town-group fetch, then single-process compile + reverify + new listings.

Speed comes from concurrent discovery. Accuracy comes from one merged compile,
full reverify, and URL checks before the dashboard is rebuilt.
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
from scanner.fetch import _merge_unique, _record_key, fetch_all_towns, save_raw  # noqa: E402
from scanner.new_listings import (  # noqa: E402
    compile_new_listings,
    fetch_new_listings,
    print_new_listings_summary,
    save_new_listings,
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
    parser.add_argument("--no-markdown", action="store_true")
    parser.add_argument(
        "--enable-counties",
        action="store_true",
        help="Also run county-wide for_sale sweeps (slower, more coverage)",
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

    # --- Single-process compile + full reverify (accuracy gate) ---
    previous = load_previous_compiled()
    final, stats, _ = compile_records(
        live_records,
        include_legacy=False,
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
