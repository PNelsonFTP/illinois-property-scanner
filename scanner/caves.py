"""Caves / underground bunkers / underground structures near ZIP 60189.

Regional hub discovery via HomeHarvest (no MLS keyword API), then text
evidence filtering. Shown all-or-nothing on the dashboard (no town toggles).
Drive hours are approximate: haversine miles ÷ highway_mph.
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
from scanner.geo import CITY_CENTER_COORDS, extract_coords_with_source, haversine_miles
from scanner.links import attach_alt_links
from scanner.normalize import normalize_realtor_record
from scanner.status import is_verified_active

log = logging.getLogger(__name__)

CAVES_PATH = PROJECT_ROOT / "data" / "caves_listings.json"

# Wheaton ZIP 60189 approximate center.
ZIP_60189_CENTER = (41.8661, -88.1070)

_MAN_CAVE = re.compile(r"\bman[\s-]?cave\b", re.I)
_CAVEAT = re.compile(r"\bcaveat\b", re.I)
_BUNKER_HILL = re.compile(r"\bbunker\s+hill\b", re.I)

# Strong underground / cave property signals (exceptional 8–12h band).
# Storm shelter is intentionally weak-only (see below).
_STRONG_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcave\s+home\b", re.I), "Cave"),
    (re.compile(r"\bcave\s+house\b", re.I), "Cave"),
    (re.compile(r"\bcave\s+dwelling\b", re.I), "Cave"),
    (re.compile(r"\bnatural\s+cave\b", re.I), "Cave"),
    (re.compile(r"\blimestone\s+cave\b", re.I), "Cave"),
    (re.compile(r"\bcave\s+on\s+(the\s+)?(property|lot|land)\b", re.I), "Cave"),
    (re.compile(r"\bunderground\s+bunker\b", re.I), "Bunker"),
    (re.compile(r"\bbomb\s+shelter\b", re.I), "Bunker"),
    (re.compile(r"\bfallout\s+shelter\b", re.I), "Bunker"),
    (re.compile(r"\btornado\s+bunker\b", re.I), "Bunker"),
    (re.compile(r"\bstorm\s+bunker\b", re.I), "Bunker"),
    (re.compile(r"\bunderground\s+home\b", re.I), "Underground home"),
    (re.compile(r"\bearth[\s-]?sheltered\b", re.I), "Underground home"),
    (re.compile(r"\bberm\s+home\b", re.I), "Underground home"),
    (re.compile(r"\bhobbit\s+home\b", re.I), "Underground home"),
    (re.compile(r"\bsubterranean\s+(home|living|dwelling|quarters)\b", re.I), "Underground home"),
    (re.compile(r"\bunderground\s+living\s+quarters\b", re.I), "Underground home"),
]

# Place-name noise that contains "cave" / "bunker" but is not a feature.
_CAVE_PLACE_NOISE = re.compile(
    r"\b(cave\s+creek|cave\s+city|cave\s+spring|mammoth\s+cave|"
    r"cave\s+run|lost\s+river\s+cave)\b",
    re.I,
)

# Weak patterns that require a nearby underground cue (window match).
# Root cellar / wine cellar / bare bunker need a co-signal in-window.
_NEAR_UNDERGROUND = re.compile(
    r"(?:underground|subterranean|below[\s-]?ground|below\s+grade|"
    r"earth[\s-]?sheltered|cave|bunker).{0,48}"
    r"(?:wine\s+cellar|root\s+cellar|bunker)|"
    r"(?:wine\s+cellar|root\s+cellar|bunker).{0,48}"
    r"(?:underground|subterranean|below[\s-]?ground|below\s+grade|"
    r"earth[\s-]?sheltered|cave|bunker)",
    re.I,
)

_STORM_SHELTER = re.compile(
    r"\b(?:in[\s-]?ground\s+)?(?:underground\s+)?storm\s+shelter\b|"
    r"\bunderground\s+storm\s+shelter\b|"
    r"\bin[\s-]?ground\s+storm\s+shelter\b",
    re.I,
)
_PRIVATE_STORM_CUE = re.compile(
    r"\b(?:on\s+the\s+property|near\s+the\s+garage|private)\b",
    re.I,
)
_COMMUNITY_AMENITY = re.compile(
    r"\b(?:community|subdivision|amenities?\s+include|hoa)\b",
    re.I,
)

_BARE_CAVE = re.compile(r"\bcave\b", re.I)

# Cave property context (not street / tourism names).
_CAVE_PROPERTY_CUE = re.compile(
    r"\b(cave\s+(home|house|dwelling|entrance|system)|natural\s+cave|"
    r"limestone\s+cave|cave\s+on\s+(the\s+)?(property|lot|land)|"
    r"on\s+(the\s+)?(property|lot|land).{0,40}\bcave|"
    r"\bcave.{0,40}on\s+(the\s+)?(property|lot|land))\b",
    re.I,
)

_DEFAULT_HUBS = [
    "Wheaton, IL",
    "Chicago, IL",
    "Rockford, IL",
    "Peoria, IL",
    "Springfield, IL",
    "Champaign, IL",
    "Carbondale, IL",
    "St. Louis, MO",
    "Springfield, MO",
    "Branson, MO",
    "Columbia, MO",
    "Kansas City, MO",
    "Louisville, KY",
    "Lexington, KY",
    "Cave City, KY",
    "Bowling Green, KY",
    "Indianapolis, IN",
    "Evansville, IN",
    "Bloomington, IN",
    "Fort Wayne, IN",
    "Nashville, TN",
    "Memphis, TN",
    "Knoxville, TN",
    "Chattanooga, TN",
    "Little Rock, AR",
    "Fayetteville, AR",
    "Detroit, MI",
    "Grand Rapids, MI",
    "Ann Arbor, MI",
    "Lansing, MI",
]


def _caves_cfg(config: dict) -> dict[str, Any]:
    cfg = dict(config.get("caves_bunkers") or {})
    cfg.setdefault("origin_zip", "60189")
    cfg.setdefault("origin_label", "Wheaton, IL (60189)")
    cfg.setdefault("highway_mph", 55)
    cfg.setdefault("preferred_hours", 4)
    cfg.setdefault("max_hours", 8)
    cfg.setdefault("exceptional_max_hours", 12)
    cfg.setdefault("hub_radius_miles", 60)
    cfg.setdefault("states", ["IL", "MO", "AR", "KY", "IN", "TN", "MI"])
    cfg.setdefault("hubs", list(_DEFAULT_HUBS))
    return cfg


def estimate_drive_hours(
    lat: float,
    lon: float,
    *,
    highway_mph: float = 55,
    origin: tuple[float, float] = ZIP_60189_CENTER,
) -> float:
    miles = haversine_miles(origin[0], origin[1], lat, lon)
    mph = highway_mph if highway_mph > 0 else 55
    return round(miles / mph, 2)


def _text_blob(raw: dict[str, Any], normalized: dict[str, Any] | None = None) -> str:
    parts: list[str] = []
    desc = raw.get("description")
    if isinstance(desc, dict):
        parts.append(str(desc.get("text") or ""))
    elif desc:
        parts.append(str(desc))
    for detail in raw.get("details") or []:
        if isinstance(detail, dict):
            for line in detail.get("text") or []:
                parts.append(str(line))
    for tag in raw.get("tags") or []:
        parts.append(str(tag).replace("_", " "))
    if normalized:
        parts.append(str(normalized.get("notes") or ""))
        parts.append(str(normalized.get("lot_size") or ""))
    return "\n".join(p for p in parts if p)


def detect_cave_bunker_evidence(
    raw: dict[str, Any],
    normalized: dict[str, Any] | None = None,
) -> tuple[str | None, list[str], str]:
    """
    Return (feature_type, evidence snippets, strength).

    strength is ``strong`` or ``weak``. No match → (None, [], "").
    """
    blob = _text_blob(raw, normalized)
    if not blob.strip():
        return None, [], ""

    # Address kept for Bunker Hill street-name rejection (not scanned for matches).
    addr = " ".join(
        str(x)
        for x in [
            (normalized or {}).get("address"),
            raw.get("address"),
            ((raw.get("location") or {}).get("address") or {}).get("line"),
        ]
        if x
    )

    # Strip known noise phrases before matching.
    cleaned = _MAN_CAVE.sub(" ", blob)
    cleaned = _CAVEAT.sub(" ", cleaned)
    cleaned = _CAVE_PLACE_NOISE.sub(" ", cleaned)

    evidence: list[str] = []
    feature: str | None = None
    strength = ""

    for pat, label in _STRONG_PATTERNS:
        m = pat.search(cleaned)
        if m:
            feature = feature or label
            strength = "strong"
            evidence.append(m.group(0))

    if not feature:
        # Wine cellar / root cellar / bare bunker only with a nearby
        # underground / cave / earth-sheltered co-signal.
        m = _NEAR_UNDERGROUND.search(cleaned)
        if m:
            hit = m.group(0)
            if re.search(r"root\s+cellar", hit, re.I):
                feature = "Cellar"
                evidence.append("root cellar")
            elif re.search(r"wine\s+cellar", hit, re.I):
                feature = "Cellar"
                evidence.append("wine cellar")
            else:
                if _BUNKER_HILL.search(cleaned) or _BUNKER_HILL.search(addr):
                    pass
                else:
                    feature = "Bunker"
                    evidence.append("bunker")
            if feature:
                strength = "weak"

        # Storm shelter is weak-only: private-property phrasing required,
        # and community / subdivision / amenities mentions are rejected.
        if not feature and _STORM_SHELTER.search(cleaned):
            if _COMMUNITY_AMENITY.search(cleaned):
                pass
            elif _PRIVATE_STORM_CUE.search(cleaned):
                feature = "Storm shelter"
                strength = "weak"
                evidence.append("storm shelter")

        # Bare "cave" only with explicit property-context phrasing.
        if not feature and _BARE_CAVE.search(cleaned):
            cleaned_caves = _CAVE_PLACE_NOISE.sub(" ", cleaned)
            if _CAVE_PROPERTY_CUE.search(cleaned_caves):
                feature = "Cave"
                strength = "weak"
                evidence.append("cave")

    evidence = list(dict.fromkeys(evidence))[:6]
    if not feature:
        return None, [], ""
    return feature, evidence, strength


def within_drive_band(
    hours: float,
    strength: str,
    *,
    max_hours: float = 8,
    exceptional_max_hours: float = 12,
) -> bool:
    if hours <= max_hours:
        return True
    if strength == "strong" and hours <= exceptional_max_hours:
        return True
    return False


def fetch_caves_listings(config: dict) -> list[dict[str, Any]]:
    """Fetch for_sale inventory from regional hubs + light negative checks."""
    caves_cfg = _caves_cfg(config)
    scan_cfg = config.get("scan") or {}
    verify_cfg = config.get("verification") or {}
    exclude_pending = scan_cfg.get("exclude_pending", True)
    radius = float(caves_cfg["hub_radius_miles"])
    sold_days = verify_cfg.get("sold_lookback_days", 90)
    pending_days = verify_cfg.get("pending_lookback_days", 30)

    all_records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for hub in caves_cfg["hubs"]:
        batch = fetch_town_listings(
            "_caves_hub",
            hub,
            radius=radius,
            exclude_pending=exclude_pending,
            listing_type="for_sale",
            pass_name=f"caves-hub-{hub}",
        )
        for record in batch:
            record["_caves_source"] = "realtor-hub"
        added = _merge_unique(all_records, seen, batch)
        log.info("  caves hub %s unique added: %d", hub, added)

        # Land/farm pass — caves and bunkers often sit on acreage listings.
        if not caves_cfg.get("include_land_pass", True):
            time.sleep(0.2)
            continue
        land_batch = fetch_town_listings(
            "_caves_hub",
            hub,
            radius=radius,
            exclude_pending=exclude_pending,
            listing_type="for_sale",
            property_type=["land", "farm"],
            pass_name=f"caves-hub-{hub}-land",
        )
        for record in land_batch:
            record["_caves_source"] = "realtor-hub-land"
        land_added = _merge_unique(all_records, seen, land_batch)
        log.info("  caves hub %s land/farm unique added: %d", hub, land_added)
        time.sleep(0.2)

    # Negative checks on all configured hubs.
    if scan_cfg.get("include_sold_pending_checks", True):
        check_hubs = list(caves_cfg["hubs"])
        for hub in check_hubs:
            sold = fetch_town_listings(
                "_caves_neg",
                hub,
                radius=radius,
                listing_type="sold",
                past_days=sold_days,
                exclude_pending=False,
                pass_name=f"caves-sold-{hub}",
            )
            for record in sold:
                record["_negative_check"] = "sold"
                record["_caves_source"] = "realtor-sold-check"
            _merge_unique(all_records, seen, sold)

            pending = fetch_town_listings(
                "_caves_neg",
                hub,
                radius=radius,
                listing_type="pending",
                past_days=pending_days,
                exclude_pending=False,
                pass_name=f"caves-pending-{hub}",
            )
            for record in pending:
                record["_negative_check"] = "pending"
                record["_caves_source"] = "realtor-pending-check"
            _merge_unique(all_records, seen, pending)
            time.sleep(0.15)

    log.info(
        "Caves fetch complete: %d raw records (origin=%s, hub_r=%.0f mi)",
        len(all_records),
        caves_cfg.get("origin_label"),
        radius,
    )
    return all_records


def compile_caves_listings(
    raw_records: list[dict[str, Any]],
    *,
    config: dict,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Compile active listings with cave/bunker evidence inside the drive band."""
    caves_cfg = _caves_cfg(config)
    allowed_states = {str(s).upper().strip() for s in caves_cfg["states"]}
    highway_mph = float(caves_cfg["highway_mph"])
    max_hours = float(caves_cfg["max_hours"])
    exceptional_max = float(caves_cfg["exceptional_max_hours"])
    preferred = float(caves_cfg["preferred_hours"])

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

        if not (rec.get("address") or "").strip():
            stats["rejected_missing_address"] += 1
            continue

        state = (rec.get("state") or "").upper().strip()
        if state and state not in allowed_states:
            stats["rejected_out_of_state"] += 1
            continue

        feature, evidence, strength = detect_cave_bunker_evidence(raw, rec)
        if not feature:
            stats["rejected_no_evidence"] += 1
            continue

        coord_info = extract_coords_with_source(raw) or extract_coords_with_source(rec)
        if coord_info is None:
            # Last resort: city name in CITY_CENTER_COORDS
            city = (rec.get("city") or "").strip().lower()
            if city in CITY_CENTER_COORDS:
                lat, lon = CITY_CENTER_COORDS[city]
                coord_info = (lat, lon, "city_center")
            else:
                stats["rejected_no_location"] += 1
                continue

        lat, lon, coords_source = coord_info
        miles = haversine_miles(ZIP_60189_CENTER[0], ZIP_60189_CENTER[1], lat, lon)
        hours = estimate_drive_hours(lat, lon, highway_mph=highway_mph)

        if not within_drive_band(
            hours, strength, max_hours=max_hours, exceptional_max_hours=exceptional_max
        ):
            stats["rejected_too_far"] += 1
            continue

        if hours > max_hours:
            stats["accepted_exceptional_far"] += 1

        entry = {
            "address": rec.get("address", ""),
            "city": rec.get("city", ""),
            "state": rec.get("state", ""),
            "zip": rec.get("zip", ""),
            "county": rec.get("county", ""),
            "nearest_target": (rec.get("city") or "").strip().title() or "Region",
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
            "verification_source": "realtor.com-caves",
            "verification_note": reason,
            "feature_type": feature,
            "cave_evidence": evidence,
            "evidence_strength": strength,
            "drive_hours_from_60189": hours,
            "miles_from_60189": round(miles, 1),
            "preferred_band": hours <= preferred,
            "lat": lat,
            "lon": lon,
            "coords_source": coords_source,
            "needs_review": coords_source == "city_center",
            "is_cave_listing": True,
        }
        attach_alt_links(entry)
        if entry["list_price"] and entry["sqft"] and entry["sqft"] > 0:
            entry["price_per_sqft"] = round(entry["list_price"] / entry["sqft"], 2)

        accepted.append(entry)
        stats["accepted_pre_dedup"] += 1

    deduped = deduplicate(accepted)
    stats["duplicates_merged"] = len(accepted) - len(deduped)

    strength_rank = {"strong": 0, "weak": 1}
    deduped.sort(
        key=lambda p: (
            0 if p.get("preferred_band") else 1,
            p.get("drive_hours_from_60189") or 99,
            strength_rank.get(p.get("evidence_strength") or "", 9),
            p.get("list_price") is None,
            p.get("list_price") or 0,
        )
    )
    for i, record in enumerate(deduped):
        record["id"] = i + 1

    out = dict(stats)
    out["final_count"] = len(deduped)
    out["preferred_hours"] = preferred
    out["max_hours"] = max_hours
    out["exceptional_max_hours"] = exceptional_max
    out["origin_zip"] = caves_cfg["origin_zip"]
    return deduped, out


def save_caves_listings(
    records: list[dict[str, Any]],
    path: Path | None = None,
    *,
    config: dict | None = None,
) -> Path:
    out = path or CAVES_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    caves_cfg = _caves_cfg(config or {})
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(records),
        "origin_zip": caves_cfg["origin_zip"],
        "origin_label": caves_cfg["origin_label"],
        "preferred_hours": caves_cfg["preferred_hours"],
        "max_hours": caves_cfg["max_hours"],
        "exceptional_max_hours": caves_cfg["exceptional_max_hours"],
        "records": records,
    }
    with open(out, "w") as handle:
        json.dump(payload, handle, indent=2, default=str)
    log.info("Saved %d caves/bunker listings to %s", len(records), out)
    return out


def load_caves_listings(path: Path | None = None) -> list[dict[str, Any]]:
    source = path or CAVES_PATH
    if not source.exists():
        return []
    with open(source) as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return payload
    return payload.get("records", [])


def print_caves_summary(
    records: list[dict[str, Any]],
    stats: dict[str, Any],
) -> None:
    print(f"\n{'=' * 60}")
    print("CAVES & BUNKERS — underground structures near 60189")
    print(f"{'=' * 60}")
    for key, value in sorted(stats.items()):
        print(f"  {key}: {value}")

    by_feat = Counter(p.get("feature_type") for p in records)
    by_state = Counter(p.get("state") for p in records)
    preferred = sum(1 for p in records if p.get("preferred_band"))
    print(f"\nBy feature ({len(records)} total, {preferred} ≤ preferred hours):")
    for feat, count in by_feat.most_common():
        print(f"  {feat}: {count}")
    print("\nBy state:")
    for state, count in by_state.most_common():
        print(f"  {state}: {count}")
    print("\nClosest 8:")
    for p in records[:8]:
        price = f"${p['list_price']:,.0f}" if p.get("list_price") else "TBD"
        print(
            f"  ~{p.get('drive_hours_from_60189')}h · {p.get('feature_type')} · "
            f"{p.get('address')}, {p.get('city')} {p.get('state')} — {price}"
        )


def run_caves_fetch_and_save(config: dict) -> list[dict[str, Any]]:
    raw = fetch_caves_listings(config)
    save_raw(raw, label="caves-listings")
    return raw
