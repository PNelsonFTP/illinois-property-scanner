"""SSRF hardening for listing URL probes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scanner.io_records import load_records_envelope, save_records_envelope
from scanner.verify import check_listing_url, validate_listing_url_for_fetch


def test_loopback_http_rejected_without_request():
    with patch("scanner.verify.httpx.Client") as client_cls:
        ok, reason = check_listing_url("http://127.0.0.1/")
        client_cls.assert_not_called()
    assert "blocked" in reason.lower()
    assert "127.0.0.1" in reason or "forbidden" in reason.lower() or "ip" in reason.lower()
    # Inconclusive for verification; must not mark listing dead solely due to SSRF gate.
    assert ok is True


def test_private_ip_literal_rejected():
    ok, reason = validate_listing_url_for_fetch("https://10.0.0.1/listing")
    assert ok is False
    assert "forbidden" in reason.lower() or "allowlisted" in reason.lower()


def test_javascript_url_skipped_without_request():
    with patch("scanner.verify.httpx.Client") as client_cls:
        ok, reason = check_listing_url("javascript:alert(1)")
        client_cls.assert_not_called()
    assert ok is True
    assert reason == "no url to check"


def test_non_allowlisted_host_rejected_without_request():
    with patch("scanner.verify.httpx.Client") as client_cls:
        ok, reason = check_listing_url("https://evil.example/listing")
        client_cls.assert_not_called()
    assert ok is True
    assert "blocked" in reason.lower()
    assert "allowlisted" in reason.lower()


def test_realtor_https_passes_gate():
    ok, reason = validate_listing_url_for_fetch(
        "https://www.realtor.com/realestateandhomes-detail/example"
    )
    assert ok is True
    assert reason == "ok"


def test_redirect_to_allowlisted_is_inconclusive():
    mock_resp = MagicMock()
    mock_resp.status_code = 302
    mock_resp.headers = {"location": "https://www.realtor.com/other"}
    mock_resp.url = "https://www.realtor.com/start"
    mock_resp.text = ""

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.get.return_value = mock_resp

    with patch("scanner.verify.httpx.Client", return_value=mock_client):
        ok, reason = check_listing_url(
            "https://www.realtor.com/start", timeout=1.0
        )
    assert ok is True
    assert "302" in reason
    assert "inconclusive" in reason.lower()


def test_save_load_records_envelope(tmp_path):
    path = tmp_path / "records.json"
    records = [{"id": 1, "address": "1 Main"}]
    save_records_envelope(path, records, extra={"window_days": 7})
    loaded = load_records_envelope(path)
    assert loaded == records
    raw = path.read_text()
    assert "generated_at" in raw
    assert '"count": 1' in raw
    assert '"window_days": 7' in raw
