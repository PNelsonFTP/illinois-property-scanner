"""Address normalization and deduplication."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

STREET_REPLACEMENTS = [
    ("STREET", "ST"), ("AVENUE", "AVE"), ("DRIVE", "DR"), ("LANE", "LN"),
    ("ROAD", "RD"), ("BOULEVARD", "BLVD"), ("COURT", "CT"), ("PLACE", "PL"),
    ("CIRCLE", "CIR"), ("PARKWAY", "PKWY"), ("TRAIL", "TRL"),
    ("NORTH", "N"), ("SOUTH", "S"), ("EAST", "E"), ("WEST", "W"),
]


def normalize_addr(address: str, city: str = "", zip_code: str = "") -> str:
    if not address:
        return ""
    addr = address.strip().upper()
    addr = re.sub(r"\s+", " ", addr)
    for full, short in STREET_REPLACEMENTS:
        addr = re.sub(rf"\b{full}\b", short, addr)
    addr = re.sub(r"[.,#]", "", addr)
    # Keep unit numbers — different units are different properties
    addr = re.sub(r"\b(APT|APARTMENT|UNIT|STE|SUITE|#)\s*", r"\1 ", addr)
    addr = re.sub(r"\s+", " ", addr).strip()
    city = (city or "").upper().strip()
    zip_code = (zip_code or "").strip()[:5]
    return f"{addr}|{city}|{zip_code}".strip("|")


def _source_quality(record: dict[str, Any]) -> int:
    score = 0
    src = (record.get("source") or record.get("listing_source") or "").lower()
    if record.get("_raw_source") == "realtor.com":
        score += 20
    if "realtor" in src:
        score += 15
    if "redfin" in src:
        score += 12
    if record.get("mls_status"):
        score += 8
    if record.get("property_id"):
        score += 5
    if record.get("verified_at"):
        score += 5
    for v in record.values():
        if v is not None and v != "" and v != []:
            score += 1
    return score


def merge_duplicates(records: list[dict[str, Any]]) -> dict[str, Any]:
    if len(records) == 1:
        return records[0]

    records = sorted(records, key=_source_quality, reverse=True)
    merged = dict(records[0])
    all_sources: set[str] = set()
    all_urls: set[str] = set()

    for rec in records:
        src = rec.get("source") or rec.get("listing_source") or "unknown"
        all_sources.add(src)
        url = rec.get("url") or rec.get("listing_url")
        if url:
            all_urls.add(f"{src}: {url}")
        for key in [
            "list_price", "original_list_price", "beds", "baths", "sqft",
            "lot_size", "year_built", "dom", "photo_url", "price_cuts",
            "total_reduced", "mls_status", "status", "flags", "county",
            "property_id", "listing_id", "verified_at", "verification_source",
        ]:
            if (merged.get(key) is None or merged.get(key) == "" or merged.get(key) == []) and \
               rec.get(key) is not None and rec.get(key) != "":
                merged[key] = rec[key]

    merged["all_sources"] = sorted(all_sources)
    merged["all_urls"] = sorted(all_urls)
    return merged


def _dedup_key(rec: dict[str, Any]) -> str:
    """Prefer property_id; else normalized address. Empty addresses stay unique."""
    pid = rec.get("property_id")
    if pid:
        return f"pid:{pid}"
    address = (rec.get("address") or "").strip()
    if not address:
        return f"_id_{id(rec)}"
    key = normalize_addr(address, rec.get("city", ""), rec.get("zip", ""))
    if key and len(key) > 5:
        return key
    return f"_id_{id(rec)}"


def deduplicate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        groups[_dedup_key(rec)].append(rec)
    return [merge_duplicates(group) for group in groups.values()]
