"""Shared JSON envelope helpers for listing record files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def save_records_envelope(
    path: Path | str,
    records: list,
    extra: dict | None = None,
) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(records),
        "records": records,
    }
    if extra:
        payload.update(extra)
    with open(out, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return out


def load_records_envelope(path: Path | str) -> list:
    p = Path(path)
    if not p.exists():
        return []
    with open(p) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("records", [])
