"""Distress signal detection and scoring."""

from __future__ import annotations

import re
from typing import Any

DISTRESS_KEYWORDS = [
    "foreclosure", "bank owned", "bank-owned", "reo", "pre-foreclosure",
    "short sale", "as-is", "as is", "fixer", "fixer-upper",
    "investor special", "estate sale", "probate", "motivated", "must sell",
    "cash only", "cash-only", "needs work", "handyman", "below market",
    "distress", "incomplete remodel", "good bones", "vacant", "abandoned",
    "wholesale", "assignment", "tax lien", "tax deed",
]

STRONG_DISTRESS_KEYWORDS = [
    "foreclosure", "bank owned", "bank-owned", "reo", "pre-foreclosure",
    "short sale", "as-is", "as is", "fixer-upper", "fixer upper",
    "needs work", "handyman", "incomplete remodel", "cash only",
    "probate", "estate sale", "tax lien", "vacant", "abandoned",
]

STRONG_TAGS = {
    "foreclosure", "reo", "bank-owned", "bank owned", "pre-foreclosure",
    "short sale", "short-sale", "tax-lien", "tax lien", "tax-deed",
    "auction", "as-is", "as is", "fixer", "fixer-upper", "needs work",
    "handyman", "probate", "estate", "estate-sale", "vacant", "abandoned",
    "public-record", "tax-sale", "sheriff-sale", "sheriff sale", "tax sale",
}

AS_IS_TAGS = {
    "as-is", "as is", "fixer", "fixer-upper", "needs work", "handyman",
    "incomplete remodel", "good bones", "cash only", "cash-only",
}


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _safe_int(v: Any) -> int | None:
    f = _safe_float(v)
    return int(f) if f is not None else None


def extract_dom_from_details(details: list[dict] | None) -> int | None:
    if not details:
        return None
    for block in details:
        for line in block.get("text", []):
            lower = line.lower()
            if "days on market" in lower or "cumulative days on market" in lower:
                m = re.search(r":\s*(\d+)", line)
                if m:
                    return int(m.group(1))
    return None


def extract_original_price(details: list[dict] | None) -> float | None:
    if not details:
        return None
    for block in details:
        for line in block.get("text", []):
            if "original list price" in line.lower():
                m = re.search(r":\s*([\d,]+)", line)
                if m:
                    return _safe_float(m.group(1))
    return None


def extract_county(details: list[dict] | None) -> str | None:
    if not details:
        return None
    for block in details:
        for line in block.get("text", []):
            if line.lower().startswith("county:"):
                return line.split(":", 1)[1].strip()
    return None


def estimate_acres(record: dict[str, Any]) -> float | None:
    """Best-effort acres for land gating (distress path)."""
    if record.get("acres") is not None:
        try:
            return float(record["acres"])
        except (TypeError, ValueError):
            pass
    lot = str(record.get("lot_size") or "")
    m = re.search(r"([\d,.]+)\s*acres?\b", lot, re.I)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    m = re.search(r"([\d,]+)\s*sq\s*ft", lot, re.I)
    if m:
        try:
            return float(m.group(1).replace(",", "")) / 43560.0
        except ValueError:
            pass
    desc = record.get("description") or {}
    if isinstance(desc, dict) and desc.get("lot_sqft"):
        try:
            return float(desc["lot_sqft"]) / 43560.0
        except (TypeError, ValueError):
            pass
    return None


def build_text_blob(record: dict[str, Any]) -> str:
    parts = [
        record.get("notes") or "",
    ]
    desc = record.get("description")
    if isinstance(desc, dict):
        parts.append(desc.get("text") or "")
    elif desc:
        parts.append(str(desc))
    for block in record.get("details") or []:
        parts.extend(block.get("text") or [])
    for kw in record.get("distress_keywords") or []:
        parts.append(str(kw))
    return " ".join(p for p in parts if p).lower()


def is_not_distressed_flip(text: str, config: dict | None = None) -> bool:
    phrases = [
        "not a distressed sale",
        "not distressed",
        "fully renovated and move-in ready",
        "fully renovated",
        "turnkey",
        "move-in ready",
        "newly renovated",
        "beautifully maintained",
        "immaculate",
        "like new",
        "completely updated",
    ]
    if config:
        phrases.extend(p.lower() for p in config.get("not_distressed_phrases", []))
    return any(p in text for p in phrases)


def is_land_type(ptype: str) -> bool:
    p = (ptype or "").lower()
    return p in {
        "land", "farm", "lot", "vacant land", "acreage", "lots/land", "vacant lot",
    } or "land" in p or p == "farm"


def has_as_is_signal(tags: set[str], text: str) -> bool:
    if tags & AS_IS_TAGS:
        return True
    return any(t in text for t in ("as-is", "as is", "fixer", "needs work", "handyman"))


def _meaningful_price_cut(
    *,
    reduction_pct: float | None,
    price_reductions: int,
    min_publish_reduction_pct: float = 0.10,
) -> bool:
    """Publish bar for DOM+cut: ≥10% cut or ≥2 recorded reductions."""
    if reduction_pct is not None and reduction_pct >= min_publish_reduction_pct:
        return True
    if price_reductions >= 2:
        return True
    return False


def meets_publish_composite(
    tags: list[str] | set[str],
    *,
    score: int,
    text: str = "",
    config: dict | None = None,
    reduction_pct: float | None = None,
    price_reductions: int = 0,
) -> bool:
    """Require stronger evidence than DOM-only or price-cut-only."""
    cfg = (config or {}).get("distress", {})
    min_score = int(cfg.get("min_publish_score", 3))
    min_cut = float(
        cfg.get("min_meaningful_reduction_pct")
        or cfg.get("min_publish_reduction_pct", 0.10)
    )
    tagset = {t.lower() for t in tags}
    text = text or ""
    cuts = int(price_reductions or 0)

    if tagset & STRONG_TAGS or any(k in text for k in STRONG_DISTRESS_KEYWORDS):
        return True
    # high-dom + price-reduced only when the cut is meaningful (not a tiny trim).
    if "high-dom" in tagset and "price-reduced" in tagset:
        if _meaningful_price_cut(
            reduction_pct=reduction_pct,
            price_reductions=cuts,
            min_publish_reduction_pct=min_cut,
        ):
            return True
    if "high-dom" in tagset and has_as_is_signal(tagset, text):
        return True
    if score >= min_score and (
        "price-reduced" in tagset or has_as_is_signal(tagset, text) or "high-dom" in tagset
    ):
        # Score alone with only weak tags still needs a second signal beyond
        # a single DOM or single cut — require combination or strong score+as-is.
        if "high-dom" in tagset and "price-reduced" in tagset:
            if _meaningful_price_cut(
                reduction_pct=reduction_pct,
                price_reductions=cuts,
                min_publish_reduction_pct=min_cut,
            ):
                return True
        if score >= max(min_score, 5) and has_as_is_signal(tagset, text):
            return True
    return False


def detect_distress_signals(record: dict[str, Any], config: dict | None = None) -> dict[str, Any]:
    """Return distress metadata: tags, reasons, has_signal."""
    cfg = (config or {}).get("distress", {})
    high_dom = cfg.get("high_dom_days", 90)
    land_max = cfg.get("land_max_price_signal", 30000)
    mobile_max = cfg.get("mobile_max_price_signal", 50000)
    min_land_acres = float(cfg.get("min_land_acres_for_distress", 20))

    tags: set[str] = set()
    reasons: list[str] = []

    text = build_text_blob(record)
    ptype = (record.get("property_type") or "").lower()
    list_price = _safe_float(record.get("list_price"))
    dom = _safe_int(record.get("dom")) or extract_dom_from_details(record.get("details"))
    orig = _safe_float(record.get("original_list_price")) or extract_original_price(record.get("details"))
    acres = estimate_acres(record)

    # Explicit keywords from source
    for kw in record.get("distress_keywords") or []:
        if kw:
            tags.add(str(kw).lower().strip())
    for dt in record.get("distress_types") or []:
        if dt:
            tags.add(str(dt).lower().strip())

    # Text keyword scan (no bare "investor")
    for kw in DISTRESS_KEYWORDS:
        if kw not in text:
            continue
        # "below market" on sub-threshold vacant lots is noise — Large land mode owns tracts.
        if kw == "below market" and is_land_type(ptype):
            if acres is None or acres < min_land_acres:
                continue
        tags.add(kw.replace(" ", "-") if " " in kw else kw)
        reasons.append(f"keyword: {kw}")

    # Foreclosure flag / source
    flags = record.get("flags") or {}
    if flags.get("is_foreclosure") or "foreclosure" in (record.get("source") or "").lower():
        tags.add("foreclosure")
        reasons.append("foreclosure listing")

    # DOM
    if dom and dom >= high_dom:
        tags.add("high-dom")
        reasons.append(f"high DOM ({dom} days)")

    # Price reduction (2% tags for discovery; publish composite uses 10%)
    cuts = _safe_int(record.get("price_cuts", record.get("price_reductions", 0))) or 0
    total_reduced = _safe_float(record.get("total_reduced"))
    reduction_pct: float | None = None
    if orig and list_price and orig > list_price:
        reduction_pct = (orig - list_price) / orig
        if reduction_pct >= cfg.get("min_price_reduction_pct", 0.02):
            tags.add("price-reduced")
            reasons.append(f"price reduced {reduction_pct:.0%}")
            cuts = max(cuts, 1)
    elif cuts >= 1 or (total_reduced and total_reduced > 0):
        tags.add("price-reduced")
        reasons.append("price reduction recorded")

    # Auction
    if "auction" in (record.get("source") or record.get("listing_source") or "").lower():
        tags.add("auction")
        reasons.append("auction source")

    # Low price signals — land only when acreage meets large-tract threshold
    is_land = is_land_type(ptype)
    is_mobile = "mobile" in ptype or "manufactured" in ptype
    if is_land and list_price and list_price <= land_max:
        if acres is not None and acres >= min_land_acres:
            tags.add("below-market")
            reasons.append(f"large land under ${land_max:,} ({acres:g} ac)")
    elif is_mobile and list_price and list_price <= mobile_max and dom and dom >= 30:
        tags.add("below-market")
        reasons.append(f"mobile under ${mobile_max:,} with DOM")

    # Strong keyword / legal-status override for flip exclusion
    has_strong = (
        any(k in text for k in STRONG_DISTRESS_KEYWORDS)
        or bool(tags & STRONG_TAGS)
        or "foreclosure" in tags
        or "auction" in tags
        or "probate" in tags
    )
    is_flip = is_not_distressed_flip(text, config)

    # Renovated / turnkey / flip language: do not publish without a strong
    # legal distress signal (blocks high-dom + tiny-cut on flip copy).
    if is_flip and not has_strong:
        return {
            "tags": [],
            "reasons": [],
            "has_signal": False,
            "dom": dom,
            "acres": acres,
            "excluded_as_flip": True,
            "meets_publish_composite": False,
            "reduction_pct": reduction_pct,
            "price_reductions": cuts,
        }

    score_preview = calculate_score(
        {**record, "dom": dom, "price_reductions": cuts},
        sorted(tags),
    )
    publish_ok = meets_publish_composite(
        tags,
        score=score_preview,
        text=text,
        config=config,
        reduction_pct=reduction_pct,
        price_reductions=cuts,
    )

    has_signal = bool(tags) or bool(reasons)
    return {
        "tags": sorted(tags),
        "reasons": reasons,
        "has_signal": has_signal,
        "dom": dom,
        "acres": acres,
        "original_list_price": orig,
        "excluded_as_flip": False,
        "meets_publish_composite": publish_ok,
        "score_preview": score_preview,
        "reduction_pct": reduction_pct,
        "price_reductions": cuts,
    }


def calculate_score(record: dict[str, Any], tags: list[str] | None = None) -> int:
    """Weighted distress score 1-10."""
    tagset = {t.lower() for t in (tags or record.get("distress_types") or [])}
    text = build_text_blob(record)
    score = 0

    if any(t in tagset for t in ["foreclosure", "reo", "bank-owned", "bank owned", "auction"]) or "foreclosure" in text:
        score += 3
    if "pre-foreclosure" in tagset or "pre-foreclosure" in text:
        score += 2
    if "short sale" in tagset or "short sale" in text or "short-sale" in tagset:
        score += 2
    if any(t in tagset for t in ["tax-lien", "tax lien", "tax-deed"]):
        score += 3
    if any(t in tagset for t in ["estate", "estate-sale", "probate"]):
        score += 1

    dom = _safe_int(record.get("dom")) or extract_dom_from_details(record.get("details"))
    if dom:
        if dom >= 365:
            score += 3
        elif dom >= 180:
            score += 2
        elif dom >= 90:
            score += 1

    cuts = _safe_int(record.get("price_reductions", record.get("price_cuts", 0))) or 0
    if cuts >= 2:
        score += 2
    elif cuts >= 1:
        score += 1

    if any(t in tagset for t in ["below-market", "below market"]):
        score += 2

    as_is = [
        "as-is", "as is", "fixer", "fixer-upper", "cash only", "needs work",
        "good bones", "incomplete remodel",
    ]
    if any(t in tagset for t in as_is) or any(t in text for t in as_is):
        score += 2

    if any(t in tagset for t in ["vacant", "abandoned"]):
        score += 2
    if "motivated" in text:
        score += 1

    return min(max(score, 1), 10)
