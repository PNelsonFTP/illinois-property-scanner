"""Lake Holiday / investor-oriented listing features from MLS details."""

from __future__ import annotations

import re
from typing import Any

_WATERFRONT_MARKERS = (
    "waterfront",
    "lake front",
    "lakefront",
    "water front",
    "lake rights",
    "water rights",
    "canal front",
    "pond front",
    "on the lake",
    "lake frontage",
    "water frontage",
)

_HOA = re.compile(
    r"(?:hoa|association)\s*(?:fee|dues)?\s*:?\s*\$?\s*([\d,]+(?:\.\d+)?)"
    r"(?:\s*/?\s*(mo(?:nth(?:ly)?)?|yr|year(?:ly)?|annually|annual))?",
    re.I,
)
_LOT_RENT = re.compile(
    r"(?:lot\s*rent|pad\s*rent|space\s*rent)\s*:?\s*\$?\s*([\d,]+(?:\.\d+)?)",
    re.I,
)
_SUBDIV = re.compile(r"(?:subdivision|source neighborhood)\s*:\s*(.+)", re.I)
_MANUFACTURED = re.compile(
    r"\b(manufactured|mobile\s*home|mobile/manufactured|modular\s*home|"
    r"double[\s-]?wide|single[\s-]?wide)\b",
    re.I,
)


def _safe_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _monthly(amount: float, period: str | None) -> float:
    p = (period or "").lower()
    if p.startswith("yr") or p.startswith("year") or p.startswith("ann"):
        return round(amount / 12.0, 2)
    return amount


def extract_lh_features(raw_or_normalized: dict[str, Any]) -> dict[str, Any]:
    """
    Parse waterfront, HOA fee, manufactured, lot rent, subdivision
    from raw details/tags/description (or a normalized record).
    """
    record = raw_or_normalized or {}
    tags = {str(t).lower() for t in (record.get("tags") or [])}

    text_parts: list[str] = [str(record.get("notes") or "")]
    desc = record.get("description")
    if isinstance(desc, dict):
        text_parts.append(str(desc.get("text") or ""))
        ptype = str(desc.get("type") or record.get("property_type") or "").lower()
    else:
        text_parts.append(str(desc or ""))
        ptype = str(record.get("property_type") or "").lower()

    detail_lines: list[str] = []
    for block in record.get("details") or []:
        if isinstance(block, dict):
            for line in block.get("text") or []:
                detail_lines.append(str(line))
                text_parts.append(str(line))

    blob = " ".join(text_parts)
    blob_l = blob.lower()

    waterfront = any(m in blob_l for m in _WATERFRONT_MARKERS) or any(
        any(m.replace(" ", "_") in t or m in t for m in _WATERFRONT_MARKERS) for t in tags
    )

    hoa_fee = _safe_float(record.get("hoa_fee"))
    if hoa_fee is None:
        for line in detail_lines + [blob]:
            m = _HOA.search(line)
            if m:
                amount = _safe_float(m.group(1))
                if amount is not None:
                    hoa_fee = _monthly(amount, m.group(2) if m.lastindex and m.lastindex >= 2 else None)
                    # Large bare amounts in detail lines are often annual HOA
                    if m.group(2) is None and amount >= 500 and "association fee" in line.lower():
                        hoa_fee = _monthly(amount, "year")
                    break
        if hoa_fee is None and re.search(r"\bno\s+hoa\b", blob_l):
            hoa_fee = 0.0

    lot_rent = _safe_float(record.get("lot_rent_monthly") or record.get("lot_rent"))
    if lot_rent is None:
        for line in detail_lines + [blob]:
            m = _LOT_RENT.search(line)
            if m:
                lot_rent = _safe_float(m.group(1))
                if lot_rent is not None:
                    break

    manufactured = (
        "mobile" in ptype
        or "manufactured" in ptype
        or any("mobile" in t or "manufactured" in t for t in tags)
        or bool(_MANUFACTURED.search(blob))
    )

    subdivision = str(record.get("subdivision") or "").strip() or None
    if not subdivision:
        for line in detail_lines:
            m = _SUBDIV.match(line.strip())
            if m:
                subdivision = m.group(1).strip() or None
                break

    return {
        "waterfront": waterfront,
        "hoa_fee": hoa_fee,
        "manufactured": manufactured,
        "lot_rent_monthly": lot_rent,
        "subdivision": subdivision,
    }
