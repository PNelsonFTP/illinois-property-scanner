#!/usr/bin/env python3
"""Build markdown file tree from v2_compiled.json"""

from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
COMPILED = PROJECT_ROOT / "v2_compiled.json"
BASE = PROJECT_ROOT / "distressed-properties"

SCAN_DATE = os.environ.get("SCAN_DATE", "Unknown")
SCAN_TIME = os.environ.get("SCAN_TIME", "")
SCOPE = (
    "Distressed listings only — core towns ~3 mi / optional towns ~6 mi "
    "(Leland, Earlville, Waterman, Sheridan). Live-verified via Realtor.com MLS. "
    "New / pools / large-land views are dashboard-only (not this markdown tree)."
)


def load_data() -> list:
    with open(COMPILED) as f:
        return json.load(f)


def fmt_price(v):
    if v is None:
        return "N/A"
    try:
        return f"${int(v):,}"
    except Exception:
        return "TBD"


def fmt_dom(v):
    return str(int(v)) if v is not None else "N/A"


def fmt_link(url, label="Source"):
    return f"[{label}]({url})" if url else "N/A"


def sort_props(props):
    return sorted(props, key=lambda d: (-(d.get("distress_score") or 0), -(d.get("dom") or 0)))


def header_block(title, count):
    ts = f"{SCAN_DATE} at {SCAN_TIME}" if SCAN_TIME else SCAN_DATE
    return (
        f"# {title}\n\n"
        f"**Scan Date:** {ts}  \n"
        f"**Scope:** {SCOPE}  \n"
        f"**Properties:** {count}\n\n"
    )


def make_table(props, num_offset=1):
    rows = [
        "| # | Address | City | Price | Type | Distress Tags | DOM | Score | Status | Link |",
        "|---|---------|------|-------|------|---------------|-----|-------|--------|------|",
    ]
    for i, d in enumerate(props, num_offset):
        rows.append(
            f"| {i} | {d.get('address', 'Unknown')} | {d.get('nearest_target', d.get('city', ''))} "
            f"| {fmt_price(d.get('list_price'))} | {d.get('property_type', '')} "
            f"| {', '.join(d.get('distress_types', [])) or 'N/A'} "
            f"| {fmt_dom(d.get('dom'))} | {d.get('distress_score', 'N/A')} "
            f"| {d.get('status', 'N/A')} | {fmt_link(d.get('listing_url'))} |"
        )
    return "\n".join(rows) + "\n"


def make_full_table(props, num_offset=1):
    cols = [
        "#", "Address", "City", "State", "ZIP", "County", "Type",
        "Price", "Orig Price", "Reductions", "Total Reduced", "$/sqft",
        "Assessed", "DOM", "Beds", "Baths", "Sqft", "Lot Size",
        "Year Built", "Distress Tags", "Score", "Source", "Status",
        "MLS Status", "Verified At", "Notes", "Link",
    ]
    rows = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for i, d in enumerate(props, num_offset):
        def v(k, default=""):
            val = d.get(k)
            return str(val) if val is not None else default

        row = [
            str(i), v("address"), d.get("nearest_target", d.get("city", "")),
            v("state"), v("zip"), v("county"), v("property_type"),
            fmt_price(d.get("list_price")), fmt_price(d.get("original_list_price")),
            v("price_reductions", "0"),
            fmt_price(d.get("total_reduced")) if d.get("total_reduced") else "N/A",
            v("price_per_sqft"), fmt_price(d.get("assessed_value")),
            fmt_dom(d.get("dom")), v("beds"), v("baths"), v("sqft"),
            v("lot_size"), v("year_built"),
            ", ".join(d.get("distress_types", [])) or "N/A",
            v("distress_score"), v("listing_source"), v("status"),
            v("mls_status"), v("verified_at"),
            (d.get("notes") or "").replace("|", "\\|").replace("\n", " ")[:200],
            fmt_link(d.get("listing_url")),
        ]
        rows.append("| " + " | ".join(row) + " |")
    return "\n".join(rows) + "\n"


def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"  Wrote: {path}")


def is_foreclosure(d):
    tags = [t.lower() for t in d.get("distress_types", [])]
    src = (d.get("listing_source") or "").lower()
    return any("foreclosure" in t for t in tags) or "auction" in src


def is_as_is(d):
    tags = [t.lower() for t in d.get("distress_types", [])]
    kws = ["as-is", "as is", "fixer", "investor", "needs work", "good bones"]
    return any(any(kw in tag for kw in kws) for tag in tags)


def is_high_dom(d):
    return (d.get("dom") or 0) >= 90


def is_price_reduced(d):
    return (d.get("price_reductions") or 0) >= 1 or "price-reduced" in d.get("distress_types", [])


def is_land(d):
    return d.get("property_type") == "Land"


def is_auction(d):
    src = (d.get("listing_source") or "").lower()
    return "auction" in src or "auction" in (d.get("status") or "").lower()


def main():
    data = load_data()
    if BASE.exists():
        shutil.rmtree(BASE)

    for subdir in ["", "by-area", "by-type", "by-score", "raw"]:
        (BASE / subdir).mkdir(parents=True, exist_ok=True)

    area_map = {
        "wheaton": "Wheaton", "oswego": "Oswego", "sandwich": "Sandwich",
        "somonauk": "Somonauk", "lake-holiday": "Lake Holiday",
        "leland": "Leland", "earlville": "Earlville",
        "waterman": "Waterman", "sheridan": "Sheridan",
    }
    # Only emit area files for towns that appear in data (or always for core five)
    core = {"Wheaton", "Oswego", "Sandwich", "Somonauk", "Lake Holiday"}
    present = {d.get("nearest_target") for d in data}
    area_map = {k: v for k, v in area_map.items() if v in core or v in present}

    print("Building by-area files...")
    for slug, town in area_map.items():
        props = sort_props([d for d in data if d.get("nearest_target") == town])
        write_file(BASE / "by-area" / f"{slug}.md", header_block(f"Distressed Properties — {town}, IL", len(props)) + make_table(props))

    print("Building by-type files...")
    type_filters = {
        ("foreclosure", "Foreclosures & Bank-Owned / Auction"): is_foreclosure,
        ("as-is-fixer", "As-Is / Fixer / Investor Opportunities"): is_as_is,
        ("high-dom", "High Days-on-Market (DOM ≥ 90)"): is_high_dom,
        ("price-reduced", "Price-Reduced Listings"): is_price_reduced,
        ("land", "Land / Vacant Lots"): is_land,
        ("auction", "Auction Listings"): is_auction,
    }
    for (slug, title), fn in type_filters.items():
        props = sort_props([d for d in data if fn(d)])
        write_file(BASE / "by-type" / f"{slug}.md", header_block(f"Distressed Properties — {title}", len(props)) + make_table(props))

    print("Building by-score files...")
    high_props = sort_props([d for d in data if (d.get("distress_score") or 0) >= 4])
    write_file(BASE / "by-score" / "high-4-plus.md", header_block("High-Score Distressed Properties (Score 4+)", len(high_props)) + make_table(high_props))
    write_file(BASE / "by-score" / "all-scored.md", header_block("All Scored Properties", len(data)) + make_table(sort_props(data)))

    print("Building raw/all-properties.md...")
    write_file(BASE / "raw" / "all-properties.md", header_block("All Properties — Full Data", len(data)) + make_full_table(sort_props(data)))

    print("Building _index.md...")
    total = len(data)
    by_town = Counter(d["nearest_target"] for d in data)
    verified = sum(1 for d in data if "realtor.com" in (d.get("verification_source") or ""))
    reverified = sum(1 for d in data if d.get("verification_source") == "realtor.com-reverified")
    stale = sum(1 for d in data if d.get("is_stale"))
    ts = f"{SCAN_DATE} at {SCAN_TIME}" if SCAN_TIME else SCAN_DATE

    idx = f"# Distressed Properties Index — Illinois\n\n"
    idx += f"**Scan Date:** {ts}  \n"
    idx += f"**Scope:** {SCOPE}  \n"
    idx += f"**Total Properties:** {total}  \n"
    idx += f"**Live-Verified:** {verified}/{total}  \n"
    idx += f"**Re-verified:** {reverified}/{total}  \n"
    idx += f"**Stale:** {stale}\n\n"
    idx += "## Summary Statistics\n\n### By Town\n\n| Town | Count |\n|------|-------|\n"
    for town, cnt in sorted(by_town.items(), key=lambda x: -x[1]):
        idx += f"| {town} | {cnt} |\n"
    idx += f"\n## Top 10 Properties by Distress Score\n\n{make_table(sort_props(data)[:10])}"
    idx += "\n## Quick Links\n\n"
    for slug, town in area_map.items():
        idx += f"- [by-area/{slug}.md](by-area/{slug}.md) — {town} ({by_town.get(town, 0)} properties)\n"
    write_file(BASE / "_index.md", idx)
    print("Done!")


if __name__ == "__main__":
    main()
