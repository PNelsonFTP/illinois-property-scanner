"""County assessor / parcel search deep-links for IL underwriting."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

SUPPORTED_COUNTIES = {
    "lasalle",
    "dekalb",
    "kendall",
    "grundy",
    "lee",
    "dupage",
}

# Google/county search templates by normalized county key.
_COUNTY_SEARCH = {
    "lasalle": "https://www.google.com/search?q={q}+LaSalle+County+IL+assessor+parcel",
    "dekalb": "https://www.google.com/search?q={q}+DeKalb+County+IL+assessor+parcel",
    "kendall": "https://www.google.com/search?q={q}+Kendall+County+IL+assessor+parcel",
    "grundy": "https://www.google.com/search?q={q}+Grundy+County+IL+assessor+parcel",
    "lee": "https://www.google.com/search?q={q}+Lee+County+IL+assessor+parcel",
    "dupage": "https://www.google.com/search?q={q}+DuPage+County+IL+parcel+viewer",
}

_COUNTY_LABEL = {
    "lasalle": "LaSalle",
    "dekalb": "DeKalb",
    "kendall": "Kendall",
    "grundy": "Grundy",
    "lee": "Lee",
    "dupage": "DuPage",
}


def _normalize_county(county: Any) -> str:
    s = " ".join(str(county or "").strip().lower().split())
    s = s.replace(" county", "").replace(" co.", "").replace(".", "").strip()
    aliases = {
        "de kalb": "dekalb",
        "du page": "dupage",
        "la salle": "lasalle",
    }
    if s in aliases:
        return aliases[s]
    return s.replace(" ", "")


def _full_address(record: dict[str, Any]) -> str:
    parts = [
        str(record.get("address") or "").strip(),
        str(record.get("city") or record.get("nearest_target") or "").strip(),
        str(record.get("state") or "IL").strip(),
        str(record.get("zip") or "").strip(),
    ]
    return " ".join(p for p in parts if p)


def attach_assessor_links(record: dict[str, Any]) -> dict[str, Any]:
    """
    Set ``assessor_url`` and ``parcel_search_url`` for supported IL counties
    (LaSalle, DeKalb, Kendall, Grundy, Lee, DuPage). Unsupported counties get None.
    """
    county = _normalize_county(record.get("county"))
    addr = _full_address(record)
    template = _COUNTY_SEARCH.get(county)

    if county not in SUPPORTED_COUNTIES or not template or not addr:
        record["assessor_url"] = None
        record["parcel_search_url"] = None
        return record

    q = quote_plus(addr)
    record["assessor_url"] = template.format(q=q)

    pin = record.get("parcel_pin") or record.get("pin") or record.get("parcel_id")
    if pin:
        label = _COUNTY_LABEL.get(county, county.title())
        record["parcel_search_url"] = (
            f"https://www.google.com/search?q="
            f"{quote_plus(f'{pin} {label} County IL parcel')}"
        )
    else:
        record["parcel_search_url"] = record["assessor_url"]
    return record
