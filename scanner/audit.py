"""Rejection audit log and scan-to-scan change detection."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scanner.config import PROJECT_ROOT
from scanner.dedup import normalize_addr

log = logging.getLogger(__name__)

AUDIT_DIR = PROJECT_ROOT / "data" / "audit"
HISTORY_DIR = PROJECT_ROOT / "data" / "history"


def _ensure_dirs() -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def write_rejection_audit(
    rejections: list[dict[str, Any]],
    *,
    label: str = "compile",
) -> Path:
    """Persist every rejected listing with reason for debugging coverage."""
    _ensure_dirs()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = AUDIT_DIR / f"rejections-{label}-{ts}.json"
    payload = {
        "written_at": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "count": len(rejections),
        "rejections": rejections,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    # Also write a rolling "latest" pointer
    latest = AUDIT_DIR / f"rejections-{label}-latest.json"
    with open(latest, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    log.info("Wrote rejection audit: %s (%d entries)", path, len(rejections))
    return path


def _prop_key(p: dict[str, Any]) -> str:
    return normalize_addr(p.get("address", ""), p.get("city", ""), p.get("zip", ""))


def load_previous_compiled(path: Path | None = None) -> list[dict[str, Any]]:
    compiled = path or (PROJECT_ROOT / "v2_compiled.json")
    if not compiled.exists():
        return []
    try:
        with open(compiled) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def detect_changes(
    current: list[dict[str, Any]],
    previous: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Diff current vs previous scan.
    Categories: newly_active, went_pending_or_removed, sold_or_gone, price_cut, still_active.
    """
    prev_map = {_prop_key(p): p for p in previous if _prop_key(p)}
    curr_map = {_prop_key(p): p for p in current if _prop_key(p)}

    newly_active = []
    still_active = []
    price_cuts = []
    for key, p in curr_map.items():
        if key not in prev_map:
            newly_active.append(_summary(p))
        else:
            still_active.append(_summary(p))
            old_price = prev_map[key].get("list_price")
            new_price = p.get("list_price")
            if old_price and new_price and new_price < old_price:
                price_cuts.append({
                    **_summary(p),
                    "old_price": old_price,
                    "new_price": new_price,
                    "reduced_by": old_price - new_price,
                })

    removed = []
    for key, p in prev_map.items():
        if key not in curr_map:
            removed.append(_summary(p))

    return {
        "compared_at": datetime.now(timezone.utc).isoformat(),
        "previous_count": len(previous),
        "current_count": len(current),
        "newly_active": newly_active,
        "still_active_count": len(still_active),
        "price_cuts": price_cuts,
        "removed_or_inactive": removed,
    }


def _summary(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "address": p.get("address"),
        "city": p.get("city"),
        "nearest_target": p.get("nearest_target"),
        "list_price": p.get("list_price"),
        "status": p.get("status") or p.get("mls_status"),
        "listing_url": p.get("listing_url"),
        "distress_score": p.get("distress_score"),
    }


def save_change_report(changes: dict[str, Any]) -> Path:
    _ensure_dirs()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = HISTORY_DIR / f"changes-{ts}.json"
    with open(path, "w") as f:
        json.dump(changes, f, indent=2, default=str)
    latest = HISTORY_DIR / "changes-latest.json"
    with open(latest, "w") as f:
        json.dump(changes, f, indent=2, default=str)
    log.info(
        "Change report: +%d new, %d removed, %d price cuts → %s",
        len(changes.get("newly_active") or []),
        len(changes.get("removed_or_inactive") or []),
        len(changes.get("price_cuts") or []),
        path,
    )
    return path


def annotate_staleness(
    properties: list[dict[str, Any]],
    *,
    stale_hours: float = 48,
) -> list[dict[str, Any]]:
    """Mark properties whose verified_at / last_seen_active_at is older than stale_hours."""
    now = datetime.now(timezone.utc)
    for p in properties:
        ts = p.get("last_seen_active_at") or p.get("verified_at")
        p["is_stale"] = False
        p["stale_hours"] = None
        if not ts:
            p["is_stale"] = True
            p["stale_hours"] = None
            continue
        try:
            when = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            age_h = (now - when).total_seconds() / 3600
            p["stale_hours"] = round(age_h, 1)
            p["is_stale"] = age_h > stale_hours
        except ValueError:
            p["is_stale"] = True
    return properties


def archive_compiled_snapshot(properties: list[dict[str, Any]]) -> Path:
    _ensure_dirs()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = HISTORY_DIR / f"compiled-{ts}.json"
    with open(path, "w") as f:
        json.dump(properties, f, indent=2, default=str)
    return path
