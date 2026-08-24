"""MLS status inactive matching — backup / kick-out variants."""

from __future__ import annotations

from scanner.status import is_verified_active, is_verified_active_rental


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


def test_rental_active_ok():
    ok, reason = is_verified_active_rental(
        {"mls_status": "active", "status": "for_rent", "_listing_type_query": "for_rent"}
    )
    assert ok is True
    assert "rental" in reason


def test_rental_rejects_leased_and_for_sale():
    leased, _ = is_verified_active_rental({"status": "leased", "mls_status": "leased"})
    assert leased is False
    sale, _ = is_verified_active_rental({"status": "for_sale", "mls_status": "active"})
    assert sale is False
