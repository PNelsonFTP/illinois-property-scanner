"""Join archived compiled snapshots into per-listing price/DOM timelines."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from scanner.config import PROJECT_ROOT
from scanner.dedup import normalize_addr

log = logging.getLogger(__name__)

HISTORY_DIR = PROJECT_ROOT / "data" / "history"
HISTORY_POINT_LIMIT = 8

_COMPILED_TS_RE = re.compile(r"compiled-(\d{8}-\d{6})\.json$")


def _snapshot_stamp(path: Path) -> str:
    m = _COMPILED_TS_RE.search(path.name)
    return m.group(1) if m else path.stem


def _record_keys(record: dict[str, Any]) -> list[str]:
    """Prefer property_id; also index by normalized address for join fallback."""
    keys: list[str] = []
    pid = record.get("property_id")
    if pid:
        keys.append(f"pid:{pid}")
    addr_key = normalize_addr(
        record.get("address", ""),
        record.get("city", ""),
        record.get("zip", ""),
    )
    if addr_key:
        keys.append(f"addr:{addr_key}")
    return keys


def _load_snapshot(path: Path) -> list[dict[str, Any]]:
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Skipping bad history snapshot %s: %s", path.name, e)
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("records") or data.get("properties") or []
    return []


def load_history_timelines(
    history_dir: Path | None = None,
    *,
    max_points: int = HISTORY_POINT_LIMIT,
) -> dict[str, dict[str, list]]:
    """
    Load ``data/history/compiled-*.json`` (if dir exists) and build timelines
    keyed by property_id or address.

    Each series uses ``{"t": stamp, "v": value}`` points (last ``max_points``).
    """
    root = history_dir or HISTORY_DIR
    if not root.exists() or not root.is_dir():
        return {}

    paths = sorted(root.glob("compiled-*.json"))
    timelines: dict[str, dict[str, list]] = {}

    for path in paths:
        stamp = _snapshot_stamp(path)
        for rec in _load_snapshot(path):
            if not isinstance(rec, dict):
                continue
            keys = _record_keys(rec)
            if not keys:
                continue
            price = rec.get("list_price")
            dom = rec.get("dom")
            for key in keys:
                series = timelines.setdefault(
                    key, {"price_history": [], "dom_history": []}
                )
                if price is not None:
                    series["price_history"].append({"t": stamp, "v": price})
                if dom is not None:
                    series["dom_history"].append({"t": stamp, "v": dom})

    out: dict[str, dict[str, list]] = {}
    for key, series in timelines.items():
        out[key] = {
            "price_history": series["price_history"][-max_points:],
            "dom_history": series["dom_history"][-max_points:],
        }

    log.info(
        "Built history timelines for %d keys from %d snapshots in %s",
        len(out),
        len(paths),
        root,
    )
    return out


def _series_for_record(
    record: dict[str, Any],
    timelines: dict[str, dict[str, list]],
) -> dict[str, list] | None:
    for key in _record_keys(record):
        if key in timelines:
            return timelines[key]
    return None


def attach_history(
    records: list[dict[str, Any]],
    *,
    max_points: int = HISTORY_POINT_LIMIT,
    history_dir: Path | None = None,
    timelines: dict[str, dict[str, list]] | None = None,
) -> list[dict[str, Any]]:
    """Add ``price_history`` and ``dom_history`` (last 8 points) to each record."""
    tl = (
        timelines
        if timelines is not None
        else load_history_timelines(history_dir, max_points=max_points)
    )
    for rec in records:
        series = _series_for_record(rec, tl) if tl else None
        if series:
            rec["price_history"] = series["price_history"][-max_points:]
            rec["dom_history"] = series["dom_history"][-max_points:]
        else:
            rec.setdefault("price_history", [])
            rec.setdefault("dom_history", [])
    return records
