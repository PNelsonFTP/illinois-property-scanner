"""Geographic classification — Lake Holiday is NOT Sheridan."""

from __future__ import annotations

import re
from typing import Any

# Lake Holiday CDP includes the lake community and Wildwood subdivisions (per LaSalle County / Wikipedia).
# Sheridan village is ~6 miles south and is out of scope.
LAKE_HOLIDAY_NEIGHBORHOODS = (
    "lake holiday",
    "wildwood north",
    "wildwood south",
    "wildwood estates",
    "wildwood estates south",
    "new wildwood",
    "wildwood",
)

# Streets in Wildwood / Lake Holiday that MLS often lists under city=Sandwich.
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

CITY_TO_TOWN: dict[str, tuple[str, str]] = {
    "wheaton": ("Wheaton", "DuPage"),
    "oswego": ("Oswego", "Kendall"),
    "montgomery": ("Oswego", "Kendall"),
    "sandwich": ("Sandwich", "DeKalb"),
    "somonauk": ("Somonauk", "DeKalb"),
    "lake holiday": ("Lake Holiday", "LaSalle"),
}


def extract_location_hints(record: dict[str, Any]) -> dict[str, str]:
    """Parse neighborhood / subdivision / area from Realtor.com detail blocks."""
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

    # Wildwood mobile-home streets — MLS often lists city=Sandwich, neighborhood=Sandwich
    if city == "sandwich":
        addr = (record.get("address") or "").lower()
        wildwood_streets = ("meadowlark", "hickory ln", "poplar dr", "cedar ln", "cardinal ln")
        if any(s in addr for s in wildwood_streets):
            return True
        for marker in LAKE_HOLIDAY_STREET_MARKERS:
            if marker in place:
                return True

    return False


def is_out_of_scope_sheridan(record: dict[str, Any], hints: dict[str, str] | None = None) -> bool:
    """Sheridan village / township listings are not Lake Holiday and not in our 5-town scope."""
    city = (record.get("city") or "").strip().lower()
    if city != "sheridan":
        return False
    hints = hints or extract_location_hints(record)
    return not is_lake_holiday_area(record, hints)


def classify_town(record: dict[str, Any], config: dict | None = None) -> tuple[str | None, str | None]:
    """
    Assign a property to one of the 5 target towns.

    Uses MLS city + neighborhood/subdivision — NOT marketing copy in listing descriptions.
    """
    hints = extract_location_hints(record)
    city = (record.get("city") or "").strip().lower()

    # Sheridan is a separate community ~6 mi from Lake Holiday — exclude entirely.
    if city == "sheridan":
        return None, None

    if is_lake_holiday_area(record, hints):
        county = (config or {}).get("towns", {}).get("Lake Holiday", {}).get("county", "LaSalle")
        return "Lake Holiday", county

    if city in CITY_TO_TOWN:
        town, county = CITY_TO_TOWN[city]
        # Sandwich city already handled Lake Holiday/Wildwood above
        return town, county

    # Legacy records may embed city in address string only
    addr = (record.get("address") or "").lower()
    for key, (town, county) in CITY_TO_TOWN.items():
        if re.search(rf"\b{re.escape(key)}\b", addr):
            if town == "Lake Holiday" or is_lake_holiday_area(record, hints):
                return "Lake Holiday", county
            if key != "lake holiday":
                return town, county

    return None, None
