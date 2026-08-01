"""MLS status inactive matching — backup / kick-out variants."""

from __future__ import annotations

from scanner.status import is_verified_active


def test_take_backup_inactive():
    ok, reason = is_verified_active(
        {"mls_status": "Take Backup", "status": "for_sale"}
    )
    assert ok is False
    assert "inactive" in reason.lower() or "backup" in reason.lower()


def test_kick_out_inactive():
    ok, reason = is_verified_active(
        {"mls_status": "kick out", "status": "for_sale"}
    )
    assert ok is False
    assert "inactive" in reason.lower() or "kick" in reason.lower()


def test_active_for_sale_ok():
    ok, reason = is_verified_active(
        {"mls_status": "active", "status": "for_sale"}
    )
    assert ok is True
