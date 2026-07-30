"""Geographic classification for core + optional towns.

Lake Holiday is NOT Sheridan. Sheridan is its own optional town.
"""

from __future__ import annotations

import math
import re
from typing import Any

# Approx community center used for large-land radius searches.
LAKE_HOLIDAY_CENTER = (41.62617, -88.69912)

# City-center fallbacks when a listing has no lat/lon (IL land ring).
CITY_CENTER_COORDS: dict[str, tuple[float, float]] = {
    "lake holiday": LAKE_HOLIDAY_CENTER,
    "sandwich": (41.6456, -88.6217),
    "somonauk": (41.6336, -88.6812),
    "sheridan": (41.5253, -88.6795),
    "leland": (41.6145, -88.7998),
    "earlville": (41.5895, -88.9223),
    "waterman": (41.7706, -88.7737),
    "oswego": (41.6828, -88.3515),
    "yorkville": (41.6411, -88.4473),
    "plano": (41.6628, -88.5367),
    "montgomery": (41.7306, -88.3459),
    "marseilles": (41.3320, -88.7012),
    "ottawa": (41.3456, -88.8426),
    "peru": (41.3275, -89.1289),
    "lasalle": (41.3389, -89.0945),
    "la salle": (41.3389, -89.0945),
    "utica": (41.3406, -89.0095),
    "streator": (41.1209, -88.8353),
    "oglesby": (41.2956, -89.0595),
    "dekalb": (41.9295, -88.7504),
    "dek alb": (41.9295, -88.7504),
    "sycamore": (41.9889, -88.6867),
    "genoa": (42.0972, -88.6929),
    "kingston": (42.0986, -88.7665),
    "kirkland": (42.0925, -88.8504),
    "hinckley": (41.7689, -88.6412),
    "minooka": (41.4553, -88.2617),
    "morris": (41.3573, -88.4212),
    "coal city": (41.2878, -88.2856),
    "amboy": (41.7142, -89.3318),
    "dixon": (41.8389, -89.4795),
    "mendota": (41.5470, -89.1176),
    "serena": (41.4875, -88.7390),
    "millington": (41.5625, -88.5970),
    "newark": (41.5367, -88.5834),
    "lisbon": (41.4814, -88.4823),
    "big rock": (41.7639, -88.5370),
    "cortland": (41.9200, -88.6887),
    "malta": (41.9292, -88.8626),
    "paw paw": (41.6889, -88.9812),
    "comppton": (41.6953, -89.0859),
    "compton": (41.6953, -89.0859),
}

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


def haversine_miles(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Great-circle distance in miles."""
    radius = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def extract_coords(record: dict[str, Any]) -> tuple[float, float] | None:
    """Pull lat/lon from a raw Realtor record or a normalized record."""
    if record.get("lat") is not None and record.get("lon") is not None:
        try:
            return float(record["lat"]), float(record["lon"])
        except (TypeError, ValueError):
            pass

    loc = record.get("location") or {}
    addr = loc.get("address") if isinstance(loc, dict) else {}
    coord = (addr or {}).get("coordinate") if isinstance(addr, dict) else None
    if isinstance(coord, dict):
        lat, lon = coord.get("lat"), coord.get("lon")
        if lat is not None and lon is not None:
            try:
                return float(lat), float(lon)
            except (TypeError, ValueError):
                pass

    city = (record.get("city") or "").strip().lower()
    if city in CITY_CENTER_COORDS:
        return CITY_CENTER_COORDS[city]
    return None


def miles_from_lake_holiday(record: dict[str, Any]) -> float | None:
    coords = extract_coords(record)
    if not coords:
        return None
    return haversine_miles(
        LAKE_HOLIDAY_CENTER[0],
        LAKE_HOLIDAY_CENTER[1],
        coords[0],
        coords[1],
    )


def nearest_configured_town(
    record: dict[str, Any],
    config: dict | None = None,
) -> str | None:
    """Closest configured scanner town by city-center / listing coords."""
    coords = extract_coords(record)
    if not coords:
        return None
    towns = enabled_towns(config or {}, include_optional=True)
    best_name: str | None = None
    best_dist = float("inf")
    for name, zone in towns.items():
        city_key = (zone.get("cities") or [name.lower()])[0].lower()
        center = CITY_CENTER_COORDS.get(city_key) or CITY_CENTER_COORDS.get(name.lower())
        if not center:
            continue
        dist = haversine_miles(coords[0], coords[1], center[0], center[1])
        if dist < best_dist:
            best_dist = dist
            best_name = name
    return best_name


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
