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
    "wheaton": (41.8661, -88.1070),
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
    "yorkville": ("Yorkville", "Kendall"),
    "plano": ("Plano", "Kendall"),
    "hinckley": ("Hinckley", "DeKalb"),
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


def extract_coords_with_source(
    record: dict[str, Any],
) -> tuple[float, float, str] | None:
    """
    Pull lat/lon plus source tag.

    Source is ``listing`` when coordinates come from the record / MLS
    coordinate block, or ``city_center`` when falling back to CITY_CENTER_COORDS.
    """
    if record.get("lat") is not None and record.get("lon") is not None:
        try:
            lat, lon = float(record["lat"]), float(record["lon"])
            source = record.get("coords_source")
            if source not in ("listing", "city_center"):
                source = "listing"
            return lat, lon, source
        except (TypeError, ValueError):
            pass

    loc = record.get("location") or {}
    addr = loc.get("address") if isinstance(loc, dict) else {}
    coord = (addr or {}).get("coordinate") if isinstance(addr, dict) else None
    if isinstance(coord, dict):
        lat, lon = coord.get("lat"), coord.get("lon")
        if lat is not None and lon is not None:
            try:
                return float(lat), float(lon), "listing"
            except (TypeError, ValueError):
                pass

    city = (record.get("city") or "").strip().lower()
    if city in CITY_CENTER_COORDS:
        lat, lon = CITY_CENTER_COORDS[city]
        return lat, lon, "city_center"
    return None


def extract_coords(record: dict[str, Any]) -> tuple[float, float] | None:
    """Pull lat/lon from a raw Realtor record or a normalized record."""
    result = extract_coords_with_source(record)
    if result is None:
        return None
    return result[0], result[1]


def listing_zip(record: dict[str, Any]) -> str:
    return str(record.get("zip") or "").strip()[:5]


def town_zip_set(town_name: str, config: dict | None = None) -> set[str]:
    """Configured USPS ZIPs for a scanner town (empty if none listed)."""
    config = config or {}
    towns = enabled_towns(config, include_optional=True)
    zone = towns.get(town_name)
    if not zone:
        for name, candidate in towns.items():
            if name.lower() == town_name.lower():
                zone = candidate
                break
    if not zone:
        return set()
    return {str(z).strip()[:5] for z in (zone.get("zips") or []) if str(z).strip()}


def _zip_to_towns(config: dict | None) -> dict[str, list[tuple[str, str]]]:
    """Map ZIP → [(town, county), ...] from enabled town configs."""
    mapping: dict[str, list[tuple[str, str]]] = {}
    towns = enabled_towns(config or {}, include_optional=True)
    for name, zone in towns.items():
        county = zone.get("county", "")
        for zip_code in zone.get("zips") or []:
            key = str(zip_code).strip()[:5]
            if key:
                mapping.setdefault(key, []).append((name, county))
    return mapping


def _classify_by_zip(
    zip_code: str,
    zip_map: dict[str, list[tuple[str, str]]],
) -> tuple[str | None, str | None]:
    """Assign an unmapped MLS city via configured ZIP.

    Shared ZIPs (60548 Sandwich/LH, 60552 Somonauk/LH) resolve to the non-LH
    town — Lake Holiday is handled first via street/subdivision heuristics.
    """
    if not zip_code:
        return None, None
    candidates = zip_map.get(zip_code) or []
    if not candidates:
        return None, None
    names = {town for town, _ in candidates}
    if "Sandwich" in names and "Lake Holiday" in names:
        for town, county in candidates:
            if town == "Sandwich":
                return town, county
    if "Somonauk" in names and "Lake Holiday" in names:
        for town, county in candidates:
            if town == "Somonauk":
                return town, county
    return candidates[0]


def within_town_radius(
    record: dict[str, Any],
    town_name: str,
    config: dict | None = None,
) -> bool:
    """
    True if the listing belongs in the town's publish radius.

    A configured town ZIP is sufficient — Oswego 60543 / Montgomery 60538
    extend well past a 3-mile city-center circle. Haversine is only used
    to reject city-name bleed (Carol Stream labeled Wheaton, Somonauk St
    in Sycamore) when the ZIP is not one of the town's ZIPs.
    """
    config = config or {}
    towns = enabled_towns(config, include_optional=True)
    zone = towns.get(town_name)
    resolved_name = town_name
    if not zone:
        for name, candidate in towns.items():
            if name.lower() == town_name.lower():
                zone = candidate
                resolved_name = name
                break
    if not zone:
        return False

    zip_code = listing_zip(record)
    allowed_zips = town_zip_set(resolved_name, config)
    if zip_code and allowed_zips and zip_code in allowed_zips:
        return True

    scan = config.get("scan") or {}
    optional_names = {(n or "").lower() for n in (config.get("optional_towns") or {})}
    is_optional = resolved_name.lower() in optional_names
    default_r = float(
        scan.get("rural_radius_miles", 6) if is_optional else scan.get("radius_miles", 3)
    )
    radius = float(zone.get("radius_miles") or default_r)

    # Only enforce when MLS/listing coords exist. City-center fallbacks use the
    # listing's MLS city (e.g. Sandwich for Wildwood), which is often the wrong
    # center for a classified town like Lake Holiday — don't false-reject those.
    coord_info = extract_coords_with_source(record)
    if not coord_info or coord_info[2] != "listing":
        return True

    centers: list[tuple[float, float]] = []
    for city in zone.get("cities") or [resolved_name.lower()]:
        center = CITY_CENTER_COORDS.get(str(city).lower().strip())
        if center and center not in centers:
            centers.append(center)
    town_center = CITY_CENTER_COORDS.get(resolved_name.lower())
    if town_center and town_center not in centers:
        centers.append(town_center)
    if not centers:
        return True

    lat, lon = coord_info[0], coord_info[1]
    return any(haversine_miles(lat, lon, c[0], c[1]) <= radius for c in centers)


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
        if town in (
            "Leland", "Earlville", "Waterman", "Sheridan",
            "Yorkville", "Plano", "Hinckley",
        ) and not include_optional:
            return None, None
        return town, county

    zip_map = _zip_to_towns(config)
    zip_code = listing_zip(record)

    # MLS city is some other place (Sycamore, Lostant, Aurora). Do not treat
    # "Somonauk St" / "Sheridan St" as the listing city. ZIP can still recover
    # unincorporated / mislabeled rows in a configured town ZIP.
    if city:
        return _classify_by_zip(zip_code, zip_map)

    # Address-embedded city only when MLS city is blank
    addr = (record.get("address") or "").lower()
    for key, (town, county) in city_map.items():
        if re.search(rf"\b{re.escape(key)}\b", addr):
            if town == "Lake Holiday" or is_lake_holiday_area(record, hints):
                return "Lake Holiday", county
            if town in (
                "Leland", "Earlville", "Waterman", "Sheridan",
                "Yorkville", "Plano", "Hinckley",
            ) and not include_optional:
                return None, None
            if key != "lake holiday":
                return town, county

    return _classify_by_zip(zip_code, zip_map)
