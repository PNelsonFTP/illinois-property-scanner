#!/usr/bin/env python3
"""
Illinois Property Scanner — sequential entry point.

Modes: distressed, new listings (7d), pools, large land, caves/bunkers (near 60189).
For faster full refreshes prefer: scripts/parallel_full_refresh.py
Publish viewing results to GitHub Pages (see docs/PUBLISHING.md).

Usage:
  python scan.py refresh quick        # Reverify + new listings
  python scan.py refresh daily        # Parallel, no counties
  python scan.py refresh full         # Parallel + counties + public records
  python scan.py --no-legacy          # Full live scan (legacy off by default)
  python scan.py --include-optional   # Force-include Leland, Earlville, Waterman, Sheridan
  python scan.py --reverify-only      # Re-verify existing distressed list (no rediscovery)
  python scan.py --verify-only        # Re-compile from latest raw (no fetch)
  python scan.py --towns Sheridan,Leland
  python scan.py --new-listings-only  # Only refresh last-N-days all-listings view
  python scan.py --pool-listings-only # Only refresh homes-with-pools view
  python scan.py --large-land-only    # Only refresh 20+ acre land near Lake Holiday
  python scan.py --caves-only         # Only refresh caves/bunkers near ZIP 60189
  python scan.py --no-new-listings|--no-pool-listings|--no-large-land|--no-caves|--no-reverify
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scanner.audit import (
    annotate_staleness,
    archive_compiled_snapshot,
    detect_changes,
    load_previous_compiled,
    save_change_report,
    write_rejection_audit,
)
from scanner.compile import compile_records, print_summary, save_compiled
from scanner.config import PROJECT_ROOT, ensure_dirs, load_config
from scanner.fetch import (
    fetch_all_towns,
    get_fetch_health,
    is_fetch_catastrophic,
    save_raw,
)
from scanner.geo import enabled_towns
from scanner.caves import (
    compile_caves_listings,
    fetch_caves_listings,
    print_caves_summary,
    save_caves_listings,
)
from scanner.large_land import (
    compile_large_land,
    fetch_large_land,
    print_large_land_summary,
    save_large_land,
)
from scanner.new_listings import (
    compile_new_listings,
    fetch_new_listings,
    print_new_listings_summary,
    save_new_listings,
)
from scanner.pool_listings import (
    compile_pool_listings,
    print_pool_listings_summary,
    save_pool_listings,
)
from scanner.verify import reverify_properties

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scan")


def scan_timestamp() -> tuple[str, str]:
    now = datetime.now(ZoneInfo("America/Chicago"))
    return now.strftime("%B %d, %Y"), now.strftime("%-I:%M %p %Z")


def rebuild_outputs(scan_date: str, scan_time: str) -> None:
    env = {"SCAN_DATE": scan_date, "SCAN_TIME": scan_time}
    for script_name in ("build_markdown.py", "build_dashboard.py"):
        script = PROJECT_ROOT / script_name
        if script.exists():
            log.info("Running %s...", script_name)
            subprocess.run(
                [sys.executable, str(script)],
                check=True,
                cwd=PROJECT_ROOT,
                env={**dict(__import__("os").environ), **env},
            )


def _run_new_listings(
    config: dict,
    *,
    include_optional: bool,
    towns_filter: list[str] | None,
    days: int,
) -> tuple[list, dict]:
    log.info("Fetching ALL new listings (last %d days, geo only)...", days)
    raw = fetch_new_listings(
        config,
        days=days,
        include_optional=include_optional,
        towns_filter=towns_filter,
    )
    save_raw(raw, label=f"new-listings-{days}d")
    records, stats = compile_new_listings(raw, config=config, days=days)
    save_new_listings(records)
    print_new_listings_summary(records, stats, days=days)
    return records, stats


def _run_pool_listings(
    config: dict,
    *,
    include_optional: bool,
    towns_filter: list[str] | None,
    raw_records: list | None = None,
) -> tuple[list, dict]:
    """Compile and reverify all active residential pool listings in scope."""
    if raw_records is None:
        log.info("Fetching active inventory for homes-with-pools view...")
        raw_records = fetch_all_towns(
            config,
            include_optional=include_optional,
            towns_filter=towns_filter,
        )
        save_raw(raw_records, label="pool-listings")

    records, stats = compile_pool_listings(raw_records, config=config)
    kept, rejected = reverify_properties(
        records,
        raw_records=raw_records,
        config=config,
        # Pool records already come from this run's live for-sale inventory.
        # Validate against sold/pending inventories without triggering another
        # immediately rate-limited Realtor fetch.
        check_urls=False,
        do_reverify=False,
        max_reverify=None,
    )
    write_rejection_audit(rejected, label="pool-validation")
    stats["validation_kept"] = len(kept)
    stats["validation_rejected"] = len(rejected)
    stats["final_count"] = len(kept)
    for i, record in enumerate(kept):
        record["id"] = i + 1
    save_pool_listings(kept)
    print_pool_listings_summary(kept, stats)
    return kept, stats


def _run_large_land(
    config: dict,
    *,
    raw_records: list | None = None,
) -> tuple[list, dict]:
    """Fetch/compile large tracts and validate against sold/pending checks."""
    if raw_records is None:
        log.info("Fetching large-land inventory (≥20 acres, 40 mi Lake Holiday)...")
        raw_records = fetch_large_land(config)
        save_raw(raw_records, label="large-land")

    records, stats = compile_large_land(raw_records, config=config)
    kept, rejected = reverify_properties(
        records,
        raw_records=raw_records,
        config=config,
        check_urls=False,
        do_reverify=False,
        max_reverify=None,
    )
    write_rejection_audit(rejected, label="large-land-validation")
    stats["validation_kept"] = len(kept)
    stats["validation_rejected"] = len(rejected)
    stats["final_count"] = len(kept)
    for i, record in enumerate(kept):
        record["id"] = i + 1
    save_large_land(kept)
    print_large_land_summary(kept, stats)
    return kept, stats


def _run_caves_listings(
    config: dict,
    *,
    raw_records: list | None = None,
) -> tuple[list, dict]:
    """Fetch/compile caves & underground bunkers near ZIP 60189."""
    if raw_records is None:
        log.info("Fetching caves/bunker inventory (hubs near ZIP 60189)...")
        raw_records = fetch_caves_listings(config)
        save_raw(raw_records, label="caves-listings")

    records, stats = compile_caves_listings(raw_records, config=config)
    kept, rejected = reverify_properties(
        records,
        raw_records=raw_records,
        config=config,
        check_urls=False,
        do_reverify=False,
        max_reverify=None,
    )
    write_rejection_audit(rejected, label="caves-validation")
    stats["validation_kept"] = len(kept)
    stats["validation_rejected"] = len(rejected)
    stats["final_count"] = len(kept)
    for i, record in enumerate(kept):
        record["id"] = i + 1
    save_caves_listings(kept, config=config)
    print_caves_summary(kept, stats)
    return kept, stats


def _run_refresh_profile(profile: str, argv_rest: list[str]) -> int:
    """Dispatch named refresh profiles from config.yaml refresh_profiles."""
    config = load_config()
    profiles = config.get("refresh_profiles") or {}
    if profile not in profiles:
        log.error(
            "Unknown refresh profile %r. Choose from: %s",
            profile,
            ", ".join(sorted(profiles)) or "(none configured)",
        )
        return 2
    cfg = profiles[profile]
    log.info("Refresh profile %s: %s", profile, cfg.get("description") or "")

    if cfg.get("use_parallel"):
        script = PROJECT_ROOT / "scripts" / "parallel_full_refresh.py"
        cmd = [sys.executable, str(script)]
        if cfg.get("enable_counties"):
            cmd.append("--enable-counties")
        if cfg.get("include_public_records"):
            cmd.append("--include-public-records")
        if not cfg.get("include_new_listings", True):
            cmd.append("--skip-new-listings")
        if not cfg.get("include_large_land", True):
            cmd.append("--skip-large-land")
        if not cfg.get("include_pool_listings", True):
            cmd.append("--skip-pool-listings")
        if not cfg.get("include_caves_listings", True):
            cmd.append("--skip-caves")
        cmd.extend(argv_rest)
        log.info("Delegating to parallel refresh: %s", " ".join(cmd))
        return subprocess.call(cmd, cwd=PROJECT_ROOT)

    # quick: reverify + optional new listings
    rc = subprocess.call(
        [sys.executable, str(PROJECT_ROOT / "scan.py"), "--reverify-only", *argv_rest],
        cwd=PROJECT_ROOT,
    )
    if rc != 0:
        return rc
    if cfg.get("include_new_listings"):
        return subprocess.call(
            [
                sys.executable,
                str(PROJECT_ROOT / "scan.py"),
                "--new-listings-only",
                "--include-optional",
                *argv_rest,
            ],
            cwd=PROJECT_ROOT,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "refresh":
        if len(argv) < 2:
            log.error("Usage: python scan.py refresh {quick,daily,full}")
            return 2
        return _run_refresh_profile(argv[1].lower(), argv[2:])

    parser = argparse.ArgumentParser(description="Distressed Property Scanner")
    parser.add_argument("--verify-only", action="store_true",
                        help="Compile from latest raw data without fetching")
    parser.add_argument("--reverify-only", action="store_true",
                        help="Re-verify existing v2_compiled.json without rediscovery")
    parser.add_argument("--new-listings-only", action="store_true",
                        help="Only refresh last-N-days all-listings view (no distress scan)")
    parser.add_argument("--pool-listings-only", action="store_true",
                        help="Only refresh active homes-with-pools view")
    parser.add_argument("--large-land-only", action="store_true",
                        help="Only refresh 20+ acre land within 40 mi of Lake Holiday")
    parser.add_argument("--caves-only", action="store_true",
                        help="Only refresh caves/bunkers near ZIP 60189")
    parser.add_argument(
        "--no-legacy",
        action="store_true",
        help="Exclude legacy v2-*.json (default behavior; kept for compatibility)",
    )
    parser.add_argument(
        "--include-legacy",
        action="store_true",
        help="Include legacy v2-*.json curated files",
    )
    parser.add_argument("--no-markdown", action="store_true", help="Skip markdown/dashboard rebuild")
    parser.add_argument("--no-reverify", action="store_true", help="Skip post-compile reverify pass")
    parser.add_argument("--no-new-listings", action="store_true",
                        help="Skip the new-listings (7-day) pass")
    parser.add_argument("--no-pool-listings", action="store_true",
                        help="Skip the homes-with-pools pass")
    parser.add_argument("--no-large-land", action="store_true",
                        help="Skip the large-land (20+ acres) pass")
    parser.add_argument("--no-caves", action="store_true",
                        help="Skip the caves/bunkers pass")
    parser.add_argument("--include-optional", action="store_true",
                        help="Include Leland, Earlville, Waterman, Sheridan")
    parser.add_argument("--no-optional", action="store_true", help="Force-exclude optional towns")
    parser.add_argument("--include-public-records", action="store_true",
                        help="Merge data/public_records/*.csv into distress compile")
    parser.add_argument("--towns", type=str, default="",
                        help="Comma-separated town filter (e.g. Sheridan,Leland)")
    parser.add_argument("--raw-file", type=Path, help="Use specific raw JSON file")
    parser.add_argument("--max-reverify", type=int, default=None,
                        help="Cap number of listings to deep-reverify")
    parser.add_argument("--new-days", type=int, default=None,
                        help="Window for new listings (default from config, usually 7)")
    args = parser.parse_args(argv)

    ensure_dirs()
    config = load_config()
    scan_cfg = config.setdefault("scan", {})

    include_optional = scan_cfg.get("include_optional_towns", False)
    if args.include_optional:
        include_optional = True
    if args.no_optional:
        include_optional = False
    config["_include_optional"] = include_optional
    scan_cfg["include_optional_towns"] = include_optional

    # Legacy off by default; opt in with --include-legacy.
    include_legacy = bool(args.include_legacy)

    towns_filter = [t.strip() for t in args.towns.split(",") if t.strip()] or None
    scan_date, scan_time = scan_timestamp()
    new_days = args.new_days or int(scan_cfg.get("new_listings_days", 7))

    # --- New listings only ---
    if args.new_listings_only:
        _run_new_listings(
            config,
            include_optional=include_optional,
            towns_filter=towns_filter,
            days=new_days,
        )
        if not args.no_markdown:
            rebuild_outputs(scan_date, scan_time)
        return 0

    # --- Pool listings only ---
    if args.pool_listings_only:
        _run_pool_listings(
            config,
            include_optional=include_optional,
            towns_filter=towns_filter,
        )
        if not args.no_markdown:
            rebuild_outputs(scan_date, scan_time)
        return 0

    # --- Large land only ---
    if args.large_land_only:
        _run_large_land(config)
        if not args.no_markdown:
            rebuild_outputs(scan_date, scan_time)
        return 0

    # --- Caves / bunkers only ---
    if args.caves_only:
        _run_caves_listings(config)
        if not args.no_markdown:
            rebuild_outputs(scan_date, scan_time)
        return 0

    # --- Reverify-only path ---
    if args.reverify_only:
        compiled_path = PROJECT_ROOT / "v2_compiled.json"
        if not compiled_path.exists():
            log.error("No v2_compiled.json — run a full scan first.")
            return 1
        with open(compiled_path) as f:
            properties = json.load(f)
        raw_records = _load_latest_raw()
        previous = list(properties)
        kept, rejected = reverify_properties(
            properties,
            raw_records=raw_records,
            config=config,
            check_urls=scan_cfg.get("check_listing_urls", True),
            do_reverify=True,
            max_reverify=args.max_reverify,
        )
        write_rejection_audit(rejected, label="reverify")
        kept = annotate_staleness(kept, stale_hours=scan_cfg.get("stale_hours", 48))
        for i, p in enumerate(kept):
            p["id"] = i + 1
        changes = detect_changes(kept, previous)
        save_change_report(changes)
        archive_compiled_snapshot(kept)
        save_compiled(kept)
        _write_meta(scan_date, scan_time, kept, {"reverify_kept": len(kept), "reverify_rejected": len(rejected)}, 0)
        print_summary(kept, {"reverify_kept": len(kept), "reverify_rejected": len(rejected)})
        if not args.no_markdown:
            rebuild_outputs(scan_date, scan_time)
        return 0

    # --- Fetch or load raw ---
    live_records: list = []
    if args.verify_only or args.raw_file:
        raw_path = args.raw_file
        if not raw_path:
            candidates = sorted((PROJECT_ROOT / "data" / "raw").glob("realtor-live-*.json"), reverse=True)
            if not candidates:
                log.error("No raw data found. Run a full scan first.")
                return 1
            raw_path = candidates[0]
        log.info("Loading raw data from %s", raw_path)
        with open(raw_path) as f:
            payload = json.load(f)
        live_records = payload.get("records", payload if isinstance(payload, list) else [])
    else:
        towns = enabled_towns(config, include_optional=include_optional)
        log.info(
            "Starting live scan of %d towns (optional=%s)%s...",
            len(towns), include_optional,
            f" filter={towns_filter}" if towns_filter else "",
        )
        live_records = fetch_all_towns(
            config, include_optional=include_optional, towns_filter=towns_filter,
        )
        save_raw(live_records)
        health = get_fetch_health()
        if is_fetch_catastrophic(live_records):
            log.error(
                "Aborting: catastrophic fetch (failed=%d empty=%d usable=0)",
                health["failed"], health["empty"],
            )
            return 1

    previous = load_previous_compiled()

    include_public = bool(args.include_public_records)
    final, stats, _compile_rejections = compile_records(
        live_records,
        include_legacy=include_legacy,
        include_public_records=include_public,
        config=config,
    )

    # --- Post-compile reverify ---
    do_reverify = (
        scan_cfg.get("reverify_after_compile", True)
        and not args.no_reverify
        and not args.verify_only
    )
    if do_reverify and final:
        kept, rejected = reverify_properties(
            final,
            raw_records=live_records,
            config=config,
            check_urls=scan_cfg.get("check_listing_urls", True),
            do_reverify=True,
            max_reverify=args.max_reverify,
        )
        write_rejection_audit(rejected, label="reverify")
        stats["reverify_kept"] = len(kept)
        stats["reverify_rejected"] = len(rejected)
        final = kept
        for i, p in enumerate(final):
            p["id"] = i + 1
        stats["final_count"] = len(final)

    final = annotate_staleness(final, stale_hours=scan_cfg.get("stale_hours", 48))
    changes = detect_changes(final, previous)
    save_change_report(changes)
    archive_compiled_snapshot(final)
    save_compiled(final)
    _write_meta(scan_date, scan_time, final, stats, len(live_records), changes)

    print_summary(final, stats)
    if changes.get("newly_active") or changes.get("removed_or_inactive"):
        print(f"\nChanges vs prior scan: +{len(changes['newly_active'])} new, "
              f"-{len(changes['removed_or_inactive'])} removed, "
              f"{len(changes['price_cuts'])} price cuts")

    # --- New listings pass (all properties, last N days, geo only) ---
    do_new = (
        scan_cfg.get("include_new_listings", True)
        and not args.no_new_listings
        and not args.verify_only
        and not args.raw_file
    )
    if do_new:
        new_records, _new_stats = _run_new_listings(
            config,
            include_optional=include_optional,
            towns_filter=towns_filter,
            days=new_days,
        )
        stats["new_listings_7d"] = len(new_records)

    # --- Homes with pools (all active residential, geo only) ---
    do_pool = (
        scan_cfg.get("include_pool_listings", True)
        and not args.no_pool_listings
        and not args.verify_only
    )
    if do_pool:
        pool_records, _pool_stats = _run_pool_listings(
            config,
            include_optional=include_optional,
            towns_filter=towns_filter,
            raw_records=live_records,
        )
        stats["pool_listings"] = len(pool_records)

    # --- Large land (≥20 acres within 40 mi of Lake Holiday) ---
    do_land = (
        scan_cfg.get("include_large_land", True)
        and not args.no_large_land
        and not args.verify_only
    )
    if do_land:
        land_records, _land_stats = _run_large_land(config)
        stats["large_land"] = len(land_records)

    # --- Caves & bunkers (multi-state ring around ZIP 60189) ---
    do_caves = (
        scan_cfg.get("include_caves_listings", True)
        and not args.no_caves
        and not args.verify_only
    )
    if do_caves:
        caves_records, _caves_stats = _run_caves_listings(config)
        stats["caves_listings"] = len(caves_records)

    if not args.no_markdown and final:
        rebuild_outputs(scan_date, scan_time)
        log.info("Dashboard: file://%s", PROJECT_ROOT / "dashboard" / "distressed-property-dashboard.html")

    return 0


def _load_latest_raw() -> list:
    candidates = sorted((PROJECT_ROOT / "data" / "raw").glob("realtor-live-*.json"), reverse=True)
    if not candidates:
        return []
    with open(candidates[0]) as f:
        payload = json.load(f)
    return payload.get("records", [])


def _write_meta(scan_date, scan_time, final, stats, live_fetched, changes=None):
    meta = {
        "scan_date": scan_date,
        "scan_time": scan_time,
        "total_properties": len(final),
        "stats": stats,
        "live_fetched": live_fetched,
        "changes": {
            "newly_active": len((changes or {}).get("newly_active") or []),
            "removed": len((changes or {}).get("removed_or_inactive") or []),
            "price_cuts": len((changes or {}).get("price_cuts") or []),
        } if changes else {},
    }
    with open(PROJECT_ROOT / "data" / "last_scan.json", "w") as f:
        json.dump(meta, f, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
