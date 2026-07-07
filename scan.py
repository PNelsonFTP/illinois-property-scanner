#!/usr/bin/env python3
"""
Distressed Property Scanner — main entry point.

Usage:
  python scan.py                  # Full live scan + compile + rebuild outputs
  python scan.py --verify-only      # Re-compile existing raw data only
  python scan.py --no-legacy        # Skip legacy v2-*.json files
  python scan.py --no-markdown      # Skip markdown regeneration
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

from scanner.compile import compile_records, print_summary, save_compiled
from scanner.config import COMPILED_PATH, PROJECT_ROOT, ensure_dirs, load_config
from scanner.fetch import fetch_all_towns, save_raw

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
    build_md = PROJECT_ROOT / "build_markdown.py"
    build_dash = PROJECT_ROOT / "build_dashboard.py"
    env = {"SCAN_DATE": scan_date, "SCAN_TIME": scan_time}

    for script in (build_md, build_dash):
        if script.exists():
            log.info("Running %s...", script.name)
            subprocess.run(
                [sys.executable, str(script)],
                check=True,
                cwd=PROJECT_ROOT,
                env={**dict(__import__("os").environ), **env},
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Distressed Property Scanner")
    parser.add_argument("--verify-only", action="store_true", help="Compile from latest raw data without fetching")
    parser.add_argument("--no-legacy", action="store_true", help="Exclude legacy v2-*.json files")
    parser.add_argument("--no-markdown", action="store_true", help="Skip markdown/dashboard rebuild")
    parser.add_argument("--raw-file", type=Path, help="Use specific raw JSON file instead of fetching")
    args = parser.parse_args()

    ensure_dirs()
    config = load_config()
    scan_date, scan_time = scan_timestamp()

    live_records: list = []

    if args.verify_only or args.raw_file:
        raw_path = args.raw_file
        if not raw_path:
            raw_dir = PROJECT_ROOT / "data" / "raw"
            candidates = sorted(raw_dir.glob("realtor-live-*.json"), reverse=True)
            if not candidates:
                log.error("No raw data found. Run a full scan first.")
                return 1
            raw_path = candidates[0]
        log.info("Loading raw data from %s", raw_path)
        with open(raw_path) as f:
            payload = json.load(f)
        live_records = payload.get("records", payload if isinstance(payload, list) else [])
    else:
        log.info("Starting live scan of %d towns...", len(config.get("towns", {})))
        live_records = fetch_all_towns(config)
        save_raw(live_records)

    final, stats = compile_records(
        live_records,
        include_legacy=not args.no_legacy,
        config=config,
    )
    save_compiled(final)

    # Write scan metadata
    meta = {
        "scan_date": scan_date,
        "scan_time": scan_time,
        "total_properties": len(final),
        "stats": stats,
        "live_fetched": len(live_records),
    }
    meta_path = PROJECT_ROOT / "data" / "last_scan.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print_summary(final, stats)

    if not args.no_markdown and final:
        rebuild_outputs(scan_date, scan_time)
        log.info("Dashboard: file://%s", PROJECT_ROOT / "dashboard" / "distressed-property-dashboard.html")

    if stats.get("rejected_inactive", 0):
        log.info("Filtered out %d inactive/pending/contingent listings", stats["rejected_inactive"])

    unverified = sum(1 for p in final if p.get("verification_source") != "realtor.com-live")
    if unverified:
        log.warning("%d properties from legacy sources — run full scan to live-verify", unverified)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
