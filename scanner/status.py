"""Live status verification for property listings."""

from __future__ import annotations

import re
from typing import Any

ACTIVE_MLS_STATUSES = {
    "active",
    "for_sale",
    "for sale",
    "new",
    "back on market",
    "price change",
    "price changed",
}

INACTIVE_MLS_STATUSES = {
    "sold",
    "closed",
    "pending",
    "contingent",
    "active contingent",
    "active under contract",
    "under contract",
    "off market",
    "off-market",
    "off_market",
    "expired",
    "withdrawn",
    "cancelled",
    "canceled",
    "coming soon",
    "hold",
    "backup",
    "kick out",
    "kick-out",
    "kick_out",
    "take backup",
    "take_backup",
}


def normalize_status(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.lower().strip())


def _inactive_set(config: dict | None = None) -> set[str]:
    inactive = set(INACTIVE_MLS_STATUSES)
    if config:
        inactive.update(normalize_status(s) for s in config.get("inactive_statuses", []))
    return inactive


def is_verified_active(record: dict[str, Any], config: dict | None = None) -> tuple[bool, str]:
    """
    Return (is_active, reason).
    Uses live MLS status and pending/contingent flags from Realtor.com data.
    Prefer flags; inactive statuses use exact normalized set membership.
    """
    inactive = _inactive_set(config)
    flags = record.get("flags") or {}

    if flags.get("is_pending"):
        return False, "pending flag set"
    if flags.get("is_contingent"):
        return False, "contingent flag set"
    if flags.get("is_coming_soon"):
        return False, "coming soon flag set"

    status = normalize_status(record.get("status"))
    mls_status = normalize_status(record.get("mls_status"))

    for field in (mls_status, status):
        if field and field in inactive:
            return False, f"status indicates inactive: {field}"

    if mls_status and mls_status not in ACTIVE_MLS_STATUSES:
        # Unknown MLS status — only accept if clearly for_sale
        if status not in ("for_sale", "active", "active - for sale"):
            return False, f"unverified mls status: {mls_status or status}"

    if status in inactive:
        return False, f"listing status: {status}"

    return True, "verified active for sale"


def is_active_legacy(record: dict[str, Any], config: dict | None = None) -> tuple[bool, str]:
    """
    Conservative check for legacy hand-curated JSON records.
    Only rejects on explicit current status, not historical note text.
    """
    inactive = _inactive_set(config)

    status = normalize_status(record.get("status"))
    if status and status in inactive:
        return False, f"legacy status: {status}"

    notes = (record.get("notes") or "").lower()
    current_patterns = [
        r"\bstatus:\s*pending\b",
        r"\bnow pending\b",
        r"\bactive under contract\b",
        r"\bcurrently pending\b",
        r"\bcurrently contingent\b",
        r"\bunder contract as of\b",
        r"\btake backup\b",
        r"\bkick[- ]?out\b",
    ]
    for pat in current_patterns:
        if re.search(pat, notes):
            return False, f"legacy notes indicate inactive"

    return True, "legacy record accepted (re-verify recommended)"
