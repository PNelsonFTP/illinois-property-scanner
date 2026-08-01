"""Load manual public-record distress candidates from CSV imports.

Drop CSV files into ``data/public_records/`` (see README there). Empty dir = no-op.
Master compile wires these into the distressed inventory.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from scanner.config import PROJECT_ROOT

log = logging.getLogger(__name__)

PUBLIC_RECORDS_DIR = PROJECT_ROOT / "data" / "public_records"


def _cell(row: dict[str, Any], *names: str) -> str:
    for name in names:
        for key, val in row.items():
            if key is None:
                continue
            if str(key).strip().lower() == name.lower():
                return str(val or "").strip()
    return ""


def _maybe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _normalize_row(row: dict[str, Any], *, source_file: str) -> dict[str, Any] | None:
    address = _cell(row, "address")
    notes = _cell(row, "notes", "note", "description")
    # Require address + notes; skip incomplete rows
    if not address or not notes:
        return None

    city = _cell(row, "city")
    state = _cell(row, "state") or "IL"
    zip_code = _cell(row, "zip", "zip_code", "postal")
    source = _cell(row, "source") or "public-record"
    pin = _cell(row, "pin", "parcel", "parcel_id", "parcel_pin")
    county = _cell(row, "county")
    property_type = _cell(row, "property_type") or "Unknown"
    list_price = _maybe_float(_cell(row, "list_price", "price"))

    rec: dict[str, Any] = {
        "address": address,
        "city": city,
        "state": state,
        "zip": zip_code,
        "county": county,
        "notes": notes,
        "source": source,
        "listing_source": "public-record",
        "distress_types": ["public-record"],
        "distress_keywords": ["public-record", source],
        "status": "Active",
        "mls_status": "",
        "property_type": property_type,
        "list_price": list_price,
        "listing_url": "",
        "url": "",
        "_raw_source": "public-record",
        "_source_file": source_file,
    }
    if pin:
        rec["pin"] = pin
        rec["parcel_pin"] = pin
        rec["parcel_id"] = pin
    return rec


def load_public_records(directory: Path | None = None) -> list[dict[str, Any]]:
    """Load and normalize all ``*.csv`` files under the public-records directory."""
    root = directory or PUBLIC_RECORDS_DIR
    if not root.exists() or not root.is_dir():
        return []

    records: list[dict[str, Any]] = []
    skipped = 0

    for path in sorted(root.glob("*.csv")):
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    log.warning("Skipping empty CSV (no header): %s", path.name)
                    continue
                for row in reader:
                    if not row or all(not str(v or "").strip() for v in row.values()):
                        continue
                    rec = _normalize_row(row, source_file=path.name)
                    if rec is None:
                        skipped += 1
                        continue
                    records.append(rec)
        except (OSError, UnicodeDecodeError, csv.Error) as e:
            log.warning("Failed to read public-records CSV %s: %s", path.name, e)

    log.info(
        "Public records: loaded %d rows from %s (%d skipped)",
        len(records),
        root,
        skipped,
    )
    return records
