"""Geographic classification for core + optional towns.

Lake Holiday is NOT Sheridan. Sheridan is its own optional town.
"""

from __future__ import annotations

import re
from typing import Any

LAKE_HOLIDAY_NEIGHBORHOODS = (
    "lake holiday",
    "wildwood north",
    "wildwood south",
    "wildwood estates",
    "wildwood estates south",
    "new wildwood",
    "wildwood",
)

LAKE_HOLIDAY_STREET_MARKERS = (
    "lake holiday",
    "holiday dr",
    "holiday drive",
    "meadowlark",
    "hickory ln",
    "poplar dr",
    "cedar ln",
    "cardinal ln",
    "suzy st",
    "erma dr",
    "linda ln",
    "lakewood dr",
    "glenda ct",
    "nova rd",
)

# Base city → (town, county). Optional towns merged from config at classify time.
CITY_TO_TOWN: dict[str, tuple[str, str]] = {
    "wheaton": ("Wheaton", "DuPage"),
    "oswego": ("Oswego", "Kendall"),
    "montgomery": ("Oswego", "Kendall"),
    "boulder hill": ("Oswego", "Kendall"),
    "sandwich": ("Sandwich", "DeKalb"),
    "somonauk": ("Somonauk", "DeKalb"),
    "lake holiday": ("Lake Holiday", "LaSalle"),
    "leland": ("Leland", "LaSalle"),
    "earlville": ("Earlville", "LaSalle"),
    "waterman": ("Waterman", "DeKalb"),
    "sheridan": ("Sheridan", "LaSalle"),
}


def _active_city_map(config: dict | None) -> dict[str, tuple[str, str]]:
    """Build city→town map from config towns + optional_towns."""
    mapping = dict(CITY_TO_TOWN)
    if not config:
        return mapping
    for section in ("towns", "optional_towns"):
        for town, zone in (config.get(section) or {}).items():
            county = zone.get("county", "")
            for city in zone.get("cities") or []:
                mapping[city.lower().strip()] = (town, county)
    return mapping


def extract_location_hints(record: dict[str, Any]) -> dict[str, str]:
    hints: dict[str, str] = {}
    for block in record.get("details") or []:
        for line in block.get("text") or []:
            lower = line.lower()
            if lower.startswith("subdivision:"):
                hints["subdivision"] = line.split(":", 1)[1].strip()
            elif lower.startswith("source neighborhood:"):
                hints["neighborhood"] = line.split(":", 1)[1].strip()
            elif lower.startswith("area:"):
                hints["area"] = line.split(":", 1)[1].strip()
    return hints


def _combined_place_text(record: dict[str, Any], hints: dict[str, str]) -> str:
    parts = [
        record.get("address") or "",
        record.get("city") or "",
        hints.get("neighborhood") or "",
        hints.get("subdivision") or "",
        hints.get("area") or "",
    ]
    return " ".join(parts).lower()


def is_lake_holiday_area(record: dict[str, Any], hints: dict[str, str] | None = None) -> bool:
    hints = hints or extract_location_hints(record)
    city = (record.get("city") or "").strip().lower()
    place = _combined_place_text(record, hints)

    if city == "lake holiday":
        return True
    for marker in LAKE_HOLIDAY_NEIGHBORHOODS:
        if marker in place:
            return True
    if "lake holiday" in place:
        return True

    if city == "sandwich":
        addr = (record.get("address") or "").lower()
        wildwood_streets = ("meadowlark", "hickory ln", "poplar dr", "cedar ln", "cardinal ln")
        if any(s in addr for s in wildwood_streets):
            return True
        for marker in LAKE_HOLIDAY_STREET_MARKERS:
            if marker in place:
                return True
    return False


def enabled_towns(config: dict, *, include_optional: bool | None = None) -> dict[str, dict]:
    """Return merged town configs (core + optional when enabled)."""
    towns = dict(config.get("towns") or {})
    use_optional = include_optional
    if use_optional is None:
        use_optional = bool((config.get("scan") or {}).get("include_optional_towns", False))
    if use_optional:
        for name, zone in (config.get("optional_towns") or {}).items():
            towns[name] = zone
    return towns


def classify_town(record: dict[str, Any], config: dict | None = None) -> tuple[str | None, str | None]:
    """
    Assign a property to a target town (core or optional).

    Uses MLS city + neighborhood/subdivision — NOT marketing copy in notes.
    Lake Holiday takes priority over Sandwich for Wildwood streets.
    Sheridan is its own town when optional towns are enabled; otherwise excluded.
    """
    hints = extract_location_hints(record)
    city = (record.get("city") or "").strip().lower()
    city_map = _active_city_map(config)

    include_optional = True
    if config is not None:
        include_optional = bool((config.get("scan") or {}).get("include_optional_towns", False))
        # Also allow if optional town appears in enabled set via runtime flag stored on config
        if config.get("_include_optional") is not None:
            include_optional = bool(config["_include_optional"])

    # Lake Holiday community (including Wildwood under Sandwich city)
    if is_lake_holiday_area(record, hints):
        county = (config or {}).get("towns", {}).get("Lake Holiday", {}).get("county", "LaSalle")
        return "Lake Holiday", county

    # Sheridan: only when optional towns enabled; never fold into Lake Holiday
    if city == "sheridan":
        if include_optional:
            return "Sheridan", city_map.get("sheridan", ("Sheridan", "LaSalle"))[1]
        return None, None

    if city in city_map:
        town, county = city_map[city]
        if town in ("Leland", "Earlville", "Waterman", "Sheridan") and not include_optional:
            return None, None
        return town, county

    # Address-embedded city (legacy / incomplete records)
    addr = (record.get("address") or "").lower()
    for key, (town, county) in city_map.items():
        if re.search(rf"\b{re.escape(key)}\b", addr):
            if town == "Lake Holiday" or is_lake_holiday_area(record, hints):
                return "Lake Holiday", county
            if town in ("Leland", "Earlville", "Waterman", "Sheridan") and not include_optional:
                return None, None
            if key != "lake holiday":
                return town, county

    return None, None
