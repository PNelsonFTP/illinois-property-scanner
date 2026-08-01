"""Deep verification: re-fetch, sold/pending negatives, dead links, consensus."""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx

from scanner.status import is_verified_active, normalize_status

log = logging.getLogger(__name__)

DEAD_PAGE_MARKERS = (
    "no longer available",
    "this listing is no longer",
    "listing has been removed",
    "off market",
    "off-market",
    "this home has been sold",
    "recently sold",
    "property not found",
    "page not found",
    "listing is pending",
    "under contract",
)


def _addr_key(address: str, city: str = "", zip_code: str = "") -> str:
    a = re.sub(r"[^a-z0-9]", "", (address or "").lower())
    c = re.sub(r"[^a-z0-9]", "", (city or "").lower())
    z = (zip_code or "")[:5]
    return f"{a}|{c}|{z}"


def build_negative_index(raw_records: list[dict[str, Any]]) -> dict[str, str]:
    """Map property_id (preferred) and address → sold|pending from negative checks."""
    index: dict[str, str] = {}
    for r in raw_records:
        neg = r.get("_negative_check")
        if not neg:
            continue
        keys: list[str] = []
        pid = str(r.get("property_id") or "")
        if pid:
            keys.append(pid)
        loc = (r.get("location") or {}).get("address") or {}
        line = loc.get("line") or r.get("address") or ""
        city = loc.get("city") or r.get("city") or ""
        zip_code = loc.get("postal_code") or r.get("zip") or ""
        addr_key = _addr_key(line, city, zip_code)
        if addr_key and len(addr_key) > 5:
            keys.append(addr_key)
        for key in keys:
            if key in index and index[key] == "sold":
                continue
            index[key] = neg
    return index


def check_against_negatives(
    record: dict[str, Any],
    negative_index: dict[str, str],
) -> tuple[bool, str]:
    pid = str(record.get("property_id") or "")
    if pid and pid in negative_index:
        return False, f"found in recent {negative_index[pid]} inventory"
    key = _addr_key(
        record.get("address", ""),
        record.get("city", ""),
        record.get("zip", ""),
    )
    if key in negative_index:
        return False, f"found in recent {negative_index[key]} inventory"
    return True, "not in sold/pending inventory"


def check_listing_url(url: str, *, timeout: float = 12.0) -> tuple[bool, str]:
    if not url or not url.startswith("http"):
        return True, "no url to check"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
            r = client.get(url)
            if r.status_code in (404, 410):
                return False, f"http {r.status_code}"
            # Realtor.com bot-protection / rate limits — not proof the listing is dead
            if r.status_code in (403, 429):
                return True, f"http {r.status_code} (blocked/rate-limited — inconclusive)"
            if r.status_code >= 500:
                return True, f"http {r.status_code} (server error — inconclusive)"

            text = (r.text or "").lower()[:80000]
            block_markers = (
                "your request could not be processed",
                "unblockrequest@realtor.com",
                "reference id is",
                "access denied",
                "attention required",
            )
            if any(m in text for m in block_markers):
                return True, "realtor block page (inconclusive)"

            for marker in DEAD_PAGE_MARKERS:
                if marker in text:
                    return False, f"page marker: {marker}"

            final = str(r.url).lower()
            if "/sold/" in final or "status=sold" in final:
                return False, "redirected to sold page"
            return True, f"http {r.status_code} ok"
    except Exception as e:
        return True, f"url check error (inconclusive): {e}"


def _index_live_for_sale(locations: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch for_sale once per location; index by property_id and address key."""
    from homeharvest import scrape_property

    by_pid: dict[str, dict] = {}
    by_addr: dict[str, dict] = {}

    for loc in locations:
        try:
            results = scrape_property(
                location=loc,
                listing_type="for_sale",
                return_type="raw",
                exclude_pending=False,
                extra_property_data=True,
                limit=500,
            )
        except Exception as e:
            log.warning("Batch reverify fetch failed for %s: %s", loc, e)
            continue

        for r in results:
            rid = str(r.get("property_id") or "")
            if rid:
                by_pid[rid] = r
            loc_addr = (r.get("location") or {}).get("address") or {}
            key = _addr_key(
                loc_addr.get("line") or "",
                loc_addr.get("city") or "",
                loc_addr.get("postal_code") or "",
            )
            if key and len(key) > 5:
                by_addr[key] = r
        time.sleep(0.25)

    return {"by_pid": by_pid, "by_addr": by_addr}


def match_live_listing(
    record: dict[str, Any],
    live_index: dict[str, dict],
    config: dict | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Match a compiled property against a pre-fetched live for_sale index."""
    by_pid = live_index.get("by_pid") or {}
    by_addr = live_index.get("by_addr") or {}

    pid = str(record.get("property_id") or "")
    hit = by_pid.get(pid) if pid else None
    if not hit:
        key = _addr_key(record.get("address", ""), record.get("city", ""), record.get("zip", ""))
        hit = by_addr.get(key)

    if not hit:
        return False, "reverify: not found in current for_sale search", {}

    flags = hit.get("flags") or {}
    status = hit.get("status") or ""
    mls = hit.get("mls_status") or ""
    fresh = {
        "status": status,
        "mls_status": mls,
        "flags": flags,
        "list_price": hit.get("list_price"),
        "href": hit.get("href"),
        "last_update_date": hit.get("last_update_date"),
    }
    active, reason = is_verified_active(
        {"status": status, "mls_status": mls, "flags": flags}, config,
    )
    if not active:
        return False, f"reverify: {reason}", fresh
    return True, f"reverify active ({mls or status})", fresh


def consensus_status(record: dict[str, Any]) -> tuple[str, str]:
    sources = record.get("all_sources") or [record.get("listing_source")]
    sources = [s for s in sources if s]
    notes = (record.get("verification_note") or "").lower()
    status = normalize_status(record.get("mls_status") or record.get("status"))

    if any(x in notes for x in ("sold", "pending", "contingent")):
        if "reverify active" in notes or status in ("active", "for_sale"):
            return "needs_review", "conflicting status signals"
        return "inactive", notes

    if len(sources) >= 2:
        return "active", f"consensus across {len(sources)} sources"
    return "active", "single-source verified"


def reverify_properties(
    properties: list[dict[str, Any]],
    *,
    raw_records: list[dict[str, Any]] | None = None,
    config: dict | None = None,
    check_urls: bool = True,
    do_reverify: bool = True,
    max_reverify: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Run verification pipeline. Batch-refetches for_sale by city/ZIP once,
    then matches each property — much faster than per-listing fetches.
    """
    config = config or {}
    verify_cfg = config.get("verification") or {}
    timeout = float(verify_cfg.get("dead_link_timeout_sec", 12))

    negative_index = build_negative_index(raw_records or [])
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    to_check = properties[:max_reverify] if max_reverify else properties
    log.info(
        "Re-verifying %d properties (url_check=%s, reverify=%s)...",
        len(to_check), check_urls, do_reverify,
    )

    live_index: dict[str, dict] = {"by_pid": {}, "by_addr": {}}
    if do_reverify and to_check:
        locations: list[str] = []
        seen_loc: set[str] = set()
        for p in to_check:
            for loc in (p.get("zip"), f"{p.get('city')}, IL" if p.get("city") else None):
                if loc and str(loc) not in seen_loc:
                    seen_loc.add(str(loc))
                    locations.append(str(loc)[:40])
        # Cap locations to avoid runaway API calls
        locations = locations[:25]
        log.info("Batch reverify: fetching for_sale for %d locations...", len(locations))
        live_index = _index_live_for_sale(locations)
        log.info(
            "  live index: %d by property_id, %d by address",
            len(live_index.get("by_pid") or {}),
            len(live_index.get("by_addr") or {}),
        )

    for i, prop in enumerate(to_check):
        reasons: list[str] = []
        ok = True

        neg_ok, neg_reason = check_against_negatives(prop, negative_index)
        if not neg_ok:
            ok = False
            reasons.append(neg_reason)

        if ok and do_reverify:
            still, rev_reason, fresh = match_live_listing(prop, live_index, config)
            prop["reverify_note"] = rev_reason
            if fresh:
                if fresh.get("mls_status"):
                    prop["mls_status"] = fresh["mls_status"]
                if fresh.get("status"):
                    prop["status"] = fresh.get("mls_status") or fresh["status"]
                if fresh.get("list_price"):
                    prop["list_price"] = fresh["list_price"]
            if not still:
                ok = False
                reasons.append(rev_reason)
            else:
                reasons.append(rev_reason)

        if ok and check_urls:
            url = prop.get("listing_url") or ""
            alive, url_reason = check_listing_url(url, timeout=timeout)
            prop["url_check_note"] = url_reason
            if not alive:
                ok = False
                reasons.append(url_reason)

        verdict, consensus_note = consensus_status(prop)
        prop["consensus"] = verdict
        prop["consensus_note"] = consensus_note
        if verdict == "inactive":
            ok = False
            reasons.append(consensus_note)
        elif verdict == "needs_review":
            prop["needs_review"] = True

        prop["last_seen_active_at"] = now if ok else prop.get("last_seen_active_at")
        prop["verified_at"] = now if ok else prop.get("verified_at")
        prop["verification_note"] = "; ".join(reasons) if reasons else prop.get("verification_note", "")

        if ok:
            if do_reverify:
                prop["verification_source"] = "realtor.com-reverified"
            kept.append(prop)
        else:
            rejected.append({
                **{k: prop.get(k) for k in ("id", "address", "city", "zip", "listing_url", "status")},
                "reject_reasons": reasons,
                "rejected_at": now,
            })

        if (i + 1) % 25 == 0:
            log.info(
                "  reverify progress: %d/%d (kept=%d, rejected=%d)",
                i + 1, len(to_check), len(kept), len(rejected),
            )

    if max_reverify and len(properties) > max_reverify:
        for prop in properties[max_reverify:]:
            prop["verification_note"] = (prop.get("verification_note") or "") + "; reverify skipped (cap)"
            kept.append(prop)

    log.info("Reverify complete: kept=%d rejected=%d", len(kept), len(rejected))
    return kept, rejected
