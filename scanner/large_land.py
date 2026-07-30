"""Large tracts of land (≥20 acres) within 40 miles of Lake Holiday, IL.

Primary discovery is Realtor.com MLS via HomeHarvest (land + farm types).
Land specialty sites (LandWatch, Lands of America) block scrapers, so each
listing gets cross-check search links instead. Sold/pending inventories are
fetched as negative checks, matching the pool/distress verification path.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scanner.config import PROJECT_ROOT
from scanner.dedup import deduplicate
from scanner.fetch import _merge_unique, fetch_town_listings, save_raw
from scanner.geo import (
    LAKE_HOLIDAY_CENTER,
    extract_coords,
    miles_from_lake_holiday,
    nearest_configured_town,
)
from scanner.links import attach_land_alt_links
from scanner.normalize import normalize_realtor_record
from scanner.status import is_verified_active

log = logging.getLogger(__name__)

LARGE_LAND_PATH = PROJECT_ROOT / "data" / "large_land.json"
LAND_TYPES = {"Land", "Farm"}
SQFT_PER_ACRE = 43560.0

# Structured MLS fields (highest trust).
_ACRES_DETAIL = re.compile(
    r"Lot Size Acres:\s*([.\d,]+)",
    re.IGNORECASE,
)
_LOT_SQFT_DETAIL = re.compile(
    r"Lot Size Square Feet:\s*([\d,.]+)",
    re.IGNORECASE,
)
# Dimensions sometimes store acreage directly: ".71 ACRE" / "3.46 ACRE".
_DIM_ACRES = re.compile(
    r"Lot Size Dimensions:\s*([.\d]+)\s*ACRES?\b",
    re.IGNORECASE,
)
# Rectangular / polygon feet dimensions: "110 X 232.7 X 110 X 232.4".
_DIM_FEET = re.compile(
    r"Lot Size Dimensions:\s*([.\d]+(?:\s*[xX×]\s*[.\d]+)+)",
    re.IGNORECASE,
)
# Marketing / free text. Capture leading-dot fractions (".58 Acre"), not "58".
_ACRES_TEXT = re.compile(
    r"(?<![\d.])(\d{1,4}(?:,\d{3})*(?:\.\d+)?|\.\d+)\s*(?:acres?|ac\b)",
    re.IGNORECASE,
)
# Community amenity mentions that are NOT the subject lot size.
_ACRES_AMENITY = re.compile(
    r"\b\d{1,4}(?:\.\d+)?\s*-?\s*(?:acres?|ac)\s+"
    r"(?:recreational\s+)?(?:lake|pond|park|golf|community|subdivision)\b",
    re.IGNORECASE,
)

# Sources trusted enough to qualify a 20+ acre tract on their own.
_TRUSTED_ACRE_SOURCES = frozenset({
    "mls_lot_size_acres",
    "description_lot_sqft",
    "mls_lot_sqft",
    "mls_dimensions_acres",
    "mls_dimensions_feet",
})
_LOT_CONTEXT = re.compile(
    r"\b(?:lot|parcel|tract|site|acreage|vacant\s+land)\b",
    re.IGNORECASE,
)


def _parse_float(value: str) -> float | None:
    try:
        return float(value.replace(",", "").strip())
    except (TypeError, ValueError, AttributeError):
        return None


def _detail_lines(raw: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for detail in raw.get("details") or []:
        if not isinstance(detail, dict):
            continue
        for value in detail.get("text") or []:
            lines.append(str(value).strip())
    return lines


def _acres_from_dimensions_feet(dim_blob: str) -> float | None:
    """Estimate acres from feet dimensions (first two sides as a rectangle)."""
    parts = [p for p in re.split(r"\s*[xX×]\s*", dim_blob) if p]
    nums: list[float] = []
    for part in parts:
        parsed = _parse_float(part)
        if parsed is not None and parsed > 0:
            nums.append(parsed)
    if len(nums) < 2:
        return None
    # Typical MLS polygon lists opposing sides; use the first length×width pair.
    sqft = nums[0] * nums[1]
    if sqft < 100:
        return None
    return round(sqft / SQFT_PER_ACRE, 4)


def _trusted_acres(raw: dict[str, Any]) -> tuple[float | None, str | None]:
    """Acreage from structured MLS fields / dimensions (not marketing copy)."""
    lines = _detail_lines(raw)

    for line in lines:
        match = _ACRES_DETAIL.match(line)
        if match:
            acres = _parse_float(match.group(1))
            if acres is not None and acres > 0:
                return acres, "mls_lot_size_acres"

    desc = raw.get("description") or {}
    lot_sqft = desc.get("lot_sqft")
    if lot_sqft:
        try:
            acres = float(lot_sqft) / SQFT_PER_ACRE
            if acres > 0:
                return round(acres, 4), "description_lot_sqft"
        except (TypeError, ValueError):
            pass

    for line in lines:
        match = _LOT_SQFT_DETAIL.match(line)
        if match:
            sqft = _parse_float(match.group(1))
            if sqft and sqft > 0:
                return round(sqft / SQFT_PER_ACRE, 4), "mls_lot_sqft"

    for line in lines:
        match = _DIM_ACRES.match(line)
        if match:
            acres = _parse_float(match.group(1))
            if acres is not None and acres > 0:
                return acres, "mls_dimensions_acres"

    for line in lines:
        match = _DIM_FEET.match(line)
        if match:
            acres = _acres_from_dimensions_feet(match.group(1))
            if acres is not None and acres > 0:
                return acres, "mls_dimensions_feet"

    return None, None


def _text_acre_candidates(blob: str) -> list[tuple[float, str, bool]]:
    """Return (acres, matched_text, looks_like_subject_lot) from free text."""
    cleaned = _ACRES_AMENITY.sub(" ", blob)
    out: list[tuple[float, str, bool]] = []
    for match in _ACRES_TEXT.finditer(cleaned):
        raw_num = match.group(1)
        acres = _parse_float(raw_num)
        if acres is None or acres <= 0 or acres > 5000:
            continue
        # Guard against residual leading-dot mishandling.
        if raw_num.startswith(".") and acres >= 1:
            continue
        window_start = max(0, match.start() - 40)
        window_end = min(len(cleaned), match.end() + 40)
        window = cleaned[window_start:window_end]
        lot_like = bool(_LOT_CONTEXT.search(window)) or raw_num.startswith(".")
        out.append((acres, match.group(0), lot_like))
    return out


def extract_acres(
    raw: dict[str, Any],
    normalized: dict[str, Any] | None = None,
) -> float | None:
    """Best-effort acreage with structured MLS fields preferred over ad copy."""
    acres, _source = extract_acres_with_source(raw, normalized)
    return acres


def extract_acres_with_source(
    raw: dict[str, Any],
    normalized: dict[str, Any] | None = None,
) -> tuple[float | None, str | None]:
    """Return (acres, source_tag). Rejects fractional-lot text misreads."""
    trusted, source = _trusted_acres(raw)
    if trusted is not None:
        return round(trusted, 2), source

    desc = raw.get("description") or {}
    text_bits = [
        str(desc.get("text") or ""),
        str((normalized or {}).get("lot_size") or ""),
        str((normalized or {}).get("notes") or ""),
        str((normalized or {}).get("address") or ""),
        str(
            ((raw.get("location") or {}).get("address") or {}).get("line") or ""
        ),
    ]
    text_bits.extend(_detail_lines(raw))
    blob = " ".join(text_bits)

    candidates = _text_acre_candidates(blob)
    if not candidates:
        return None, None

    # Prefer lot-context / leading-dot subject mentions over amenity leftovers.
    lot_candidates = [c for c in candidates if c[2]]
    pool = lot_candidates or candidates
    # Prefer the smallest plausible subject-lot mention when values conflict
    # (e.g. ".58 acre lot" vs leftover community copy). For true large tracts,
    # structured fields usually exist; text-only large tracts still pass via
    # a single dominant candidate.
    acres = max(c[0] for c in pool)
    if len(pool) > 1:
        small = [c[0] for c in pool if c[0] < 5]
        large = [c[0] for c in pool if c[0] >= 20]
        if small and large:
            # Conflicting signals without MLS acres/sqft — trust the small lot.
            acres = min(small)
            return round(acres, 2), "text_lot_conflict_prefer_small"
        if small and not large:
            acres = max(small)
        elif large:
            acres = max(large)

    return round(acres, 2), "text_description"


def _land_cfg(config: dict) -> dict[str, Any]:
    cfg = dict(config.get("large_land") or {})
    cfg.setdefault("min_acres", 20)
    cfg.setdefault("radius_miles", 40)
    cfg.setdefault(
        "property_types",
        ["land", "farm"],
    )
    cfg.setdefault(
        "counties",
        [
            "LaSalle County, IL",
            "DeKalb County, IL",
            "Kendall County, IL",
            "Grundy County, IL",
            "Lee County, IL",
        ],
    )
    cfg.setdefault(
        "hubs",
        [
            "Lake Holiday, IL",
            "Sandwich, IL",
            "Sheridan, IL",
            "Yorkville, IL",
            "Ottawa, IL",
            "DeKalb, IL",
            "Morris, IL",
            "Amboy, IL",
        ],
    )
    return cfg


def fetch_large_land(config: dict) -> list[dict[str, Any]]:
    """Fetch land/farm for_sale plus sold/pending negative checks."""
    land_cfg = _land_cfg(config)
    scan_cfg = config.get("scan") or {}
    verify_cfg = config.get("verification") or {}
    exclude_pending = scan_cfg.get("exclude_pending", True)
    sold_days = verify_cfg.get("sold_lookback_days", 90)
    pending_days = verify_cfg.get("pending_lookback_days", 30)
    property_types = land_cfg["property_types"]
    radius = float(land_cfg["radius_miles"])

    all_records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for county in land_cfg["counties"]:
        batch = fetch_town_listings(
            "_land_county",
            county,
            radius=None,
            exclude_pending=exclude_pending,
            property_type=property_types,
            pass_name=f"large-land-county-{county}",
        )
        for record in batch:
            record["_land_source"] = "realtor-county"
        _merge_unique(all_records, seen, batch)
        time.sleep(0.25)

    for hub in land_cfg["hubs"]:
        batch = fetch_town_listings(
            "_land_hub",
            hub,
            radius=radius,
            exclude_pending=exclude_pending,
            property_type=property_types,
            pass_name=f"large-land-hub-{hub}",
        )
        for record in batch:
            record["_land_source"] = "realtor-hub"
        _merge_unique(all_records, seen, batch)
        time.sleep(0.25)

    # Negative-check inventories (sold / pending) for the same footprint.
    if scan_cfg.get("include_sold_pending_checks", True):
        check_locations = list(dict.fromkeys(
            [*land_cfg["counties"], *land_cfg["hubs"][:4]]
        ))
        for location in check_locations:
            sold = fetch_town_listings(
                "_land_neg",
                location,
                radius=None if "County" in location else radius,
                listing_type="sold",
                past_days=sold_days,
                exclude_pending=False,
                property_type=property_types,
                pass_name=f"large-land-sold-{location}",
            )
            for record in sold:
                record["_negative_check"] = "sold"
                record["_land_source"] = "realtor-sold-check"
            _merge_unique(all_records, seen, sold)

            pending = fetch_town_listings(
                "_land_neg",
                location,
                radius=None if "County" in location else radius,
                listing_type="pending",
                past_days=pending_days,
                exclude_pending=False,
                property_type=property_types,
                pass_name=f"large-land-pending-{location}",
            )
            for record in pending:
                record["_negative_check"] = "pending"
                record["_land_source"] = "realtor-pending-check"
            _merge_unique(all_records, seen, pending)
            time.sleep(0.2)

    log.info(
        "Large-land fetch complete: %d raw records (center=%s, %.0f mi)",
        len(all_records),
        land_cfg.get("center", "Lake Holiday, IL"),
        radius,
    )
    return all_records


def compile_large_land(
    raw_records: list[dict[str, Any]],
    *,
    config: dict,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Compile active land/farm tracts meeting acreage + radius rules."""
    land_cfg = _land_cfg(config)
    min_acres = float(land_cfg["min_acres"])
    max_miles = float(land_cfg["radius_miles"])
    stats: Counter = Counter()
    accepted: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for raw in raw_records:
        if raw.get("_negative_check"):
            continue

        rec = normalize_realtor_record(raw)
        stats["normalized"] += 1

        active, reason = is_verified_active(rec, config)
        if not active:
            stats["rejected_inactive"] += 1
            continue

        if rec.get("property_type") not in LAND_TYPES:
            # Keep unknown only when MLS description clearly says land/farm.
            raw_type = str((raw.get("description") or {}).get("type") or "").lower()
            if raw_type not in {"land", "farm", "farms", "lot", "vacant_land"}:
                stats["rejected_non_land"] += 1
                continue

        acres, acres_source = extract_acres_with_source(raw, rec)
        if acres is None:
            stats["rejected_no_acres"] += 1
            continue
        if acres < min_acres:
            stats["rejected_under_acres"] += 1
            continue
        # Large-tract claims from marketing copy alone are easy to misread
        # (".58 Acre" → 58). Require MLS acres/sqft/dimensions, or a clear
        # text lot-size statement with no conflicting small-lot signal.
        if acres_source not in _TRUSTED_ACRE_SOURCES:
            if acres_source == "text_lot_conflict_prefer_small":
                stats["rejected_acre_conflict"] += 1
                continue
            if acres_source != "text_description":
                stats["rejected_untrusted_acres"] += 1
                continue
            # Text-only large tracts: require an explicit lot/tract cue nearby
            # (already preferred in candidate scoring) and block if dimensions
            # imply a house lot — dimensions path should have won already.
            stats["accepted_text_acres"] += 1

        miles = miles_from_lake_holiday(raw)
        if miles is None:
            # Retry with normalized city for centroid lookup.
            miles = miles_from_lake_holiday(rec)
        if miles is None:
            stats["rejected_no_location"] += 1
            continue
        if miles > max_miles:
            stats["rejected_out_of_radius"] += 1
            continue

        if not rec.get("address") and not rec.get("city"):
            stats["rejected_missing_address"] += 1
            continue

        nearest = nearest_configured_town(raw, config) or nearest_configured_town(rec, config)
        city = (rec.get("city") or "").strip()
        # Bucket by city for dashboard location toggles; fall back to nearest town.
        area_label = city.title() if city else (nearest or "Lake Holiday region")

        coords = extract_coords(raw) or extract_coords(rec)
        price = rec.get("list_price")
        price_per_acre = round(price / acres, 2) if price and acres else None

        evidence = [
            f"{acres:g} acres",
            f"acres via {acres_source}",
            f"{miles:.1f} mi from Lake Holiday",
        ]
        if rec.get("lot_size"):
            evidence.append(str(rec["lot_size"]))
        source_tag = raw.get("_land_source") or "realtor"
        evidence.append(f"source: {source_tag}")

        entry = {
            "address": rec.get("address") or f"{area_label} acreage",
            "city": city,
            "state": rec.get("state", "IL"),
            "zip": rec.get("zip", ""),
            "county": rec.get("county", ""),
            "nearest_target": area_label,
            "nearest_scanner_town": nearest,
            "property_type": rec.get("property_type", "Land"),
            "list_price": price,
            "original_list_price": rec.get("original_list_price"),
            "price_reductions": rec.get("price_reductions") or 0,
            "total_reduced": rec.get("total_reduced"),
            "price_per_sqft": None,
            "price_per_acre": price_per_acre,
            "acres": round(acres, 2),
            "acres_source": acres_source,
            "dom": rec.get("dom"),
            "beds": rec.get("beds"),
            "baths": rec.get("baths"),
            "sqft": rec.get("sqft"),
            "lot_size": (
                f"{acres:g} acres"
                if acres_source in _TRUSTED_ACRE_SOURCES
                else (rec.get("lot_size") or f"{acres:g} acres")
            ),
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
            "verification_source": "realtor.com-large-land",
            "verification_note": reason,
            "miles_from_lake_holiday": round(miles, 1),
            "lat": coords[0] if coords else None,
            "lon": coords[1] if coords else None,
            "land_evidence": evidence[:6],
            "is_large_land": True,
            "alt_sources_note": (
                "Cross-check LandWatch / Lands of America / Zillow — "
                "acreage often lists off housing sites."
            ),
        }
        attach_land_alt_links(entry)
        accepted.append(entry)
        stats["accepted_pre_dedup"] += 1

    deduped = deduplicate(accepted)
    stats["duplicates_merged"] = len(accepted) - len(deduped)
    deduped.sort(
        key=lambda p: (
            -(p.get("acres") or 0),
            p.get("list_price") is None,
            p.get("list_price") or 0,
        )
    )
    for i, record in enumerate(deduped):
        record["id"] = i + 1

    out_stats = dict(stats)
    out_stats["final_count"] = len(deduped)
    out_stats["center_lat"] = LAKE_HOLIDAY_CENTER[0]
    out_stats["center_lon"] = LAKE_HOLIDAY_CENTER[1]
    out_stats["min_acres"] = min_acres
    out_stats["radius_miles"] = max_miles
    return deduped, out_stats


def save_large_land(
    records: list[dict[str, Any]],
    path: Path | None = None,
) -> Path:
    out = path or LARGE_LAND_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(records),
        "center": "Lake Holiday, IL",
        "min_acres": 20,
        "radius_miles": 40,
        "records": records,
    }
    with open(out, "w") as handle:
        json.dump(payload, handle, indent=2, default=str)
    log.info("Saved %d large-land listings to %s", len(records), out)
    return out


def load_large_land(path: Path | None = None) -> list[dict[str, Any]]:
    source = path or LARGE_LAND_PATH
    if not source.exists():
        return []
    with open(source) as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return payload
    return payload.get("records", [])


def print_large_land_summary(
    records: list[dict[str, Any]],
    stats: dict[str, Any],
) -> None:
    print(f"\n{'=' * 60}")
    print("LARGE LAND — ≥20 acres within 40 mi of Lake Holiday")
    print(f"{'=' * 60}")
    for key, value in sorted(stats.items()):
        print(f"  {key}: {value}")

    by_city = Counter(p["nearest_target"] for p in records)
    print(f"\nBy City ({len(records)} total):")
    for city, count in by_city.most_common():
        print(f"  {city}: {count}")
    if records:
        acres = [p["acres"] for p in records if p.get("acres")]
        print(
            f"\nAcreage: min={min(acres):g}  median="
            f"{sorted(acres)[len(acres)//2]:g}  max={max(acres):g}"
        )


def run_large_land_fetch_and_save(config: dict) -> list[dict[str, Any]]:
    """Convenience: fetch raw land inventory and persist a timestamped dump."""
    raw = fetch_large_land(config)
    save_raw(raw, label="large-land")
    return raw
