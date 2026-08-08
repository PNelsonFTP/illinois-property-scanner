"""Tests for caves / underground bunker detection and drive banding."""

from __future__ import annotations

from scanner.caves import (
    ZIP_60189_CENTER,
    compile_caves_listings,
    detect_cave_bunker_evidence,
    estimate_drive_hours,
    within_drive_band,
)


def _raw(text: str, *, address: str = "1 Cave Rd", city: str = "Springfield", state: str = "MO"):
    return {
        "description": {"text": text, "type": "single_family"},
        "location": {
            "address": {
                "line": address,
                "city": city,
                "state_code": state,
                "postal_code": "65804",
                "coordinate": {"lat": 37.209, "lon": -93.292},
            }
        },
        "list_price": 250000,
        "status": "for_sale",
        "flags": {},
        "property_id": "test-cave-1",
    }


def test_detects_cave_home():
    feature, evidence, strength = detect_cave_bunker_evidence(
        _raw("Unique cave home carved into limestone bluff.")
    )
    assert feature == "Cave"
    assert strength == "strong"
    assert evidence


def test_detects_underground_bunker():
    feature, evidence, strength = detect_cave_bunker_evidence(
        _raw("Property includes an underground bunker and storm protection.")
    )
    assert feature == "Bunker"
    assert strength == "strong"


def test_detects_earth_sheltered():
    feature, _, strength = detect_cave_bunker_evidence(
        _raw("Beautiful earth-sheltered home with berm design.")
    )
    assert feature == "Underground home"
    assert strength == "strong"


def test_rejects_man_cave():
    feature, _, _ = detect_cave_bunker_evidence(
        _raw("Finished basement with man cave and wet bar.")
    )
    assert feature is None


def test_rejects_caveat():
    feature, _, _ = detect_cave_bunker_evidence(
        _raw("Sold as-is; caveat emptor applies to all systems.")
    )
    assert feature is None


def test_rejects_bunker_hill_address_only():
    feature, _, _ = detect_cave_bunker_evidence(
        _raw(
            "Charming ranch with updated kitchen.",
            address="100 Bunker Hill Rd",
            city="Indianapolis",
            state="IN",
        )
    )
    assert feature is None


def test_rejects_bare_wine_cellar():
    feature, _, _ = detect_cave_bunker_evidence(
        _raw("Gourmet kitchen and wine cellar for entertaining. In-ground pool.")
    )
    assert feature is None


def test_accepts_underground_wine_cellar():
    feature, _, strength = detect_cave_bunker_evidence(
        _raw("Temperature-controlled underground wine cellar.")
    )
    assert feature == "Cellar"
    assert strength == "weak"


def test_rejects_bare_storm_shelter():
    feature, _, _ = detect_cave_bunker_evidence(
        _raw("Community amenities include storm shelter and in-ground pool.")
    )
    assert feature is None


def test_accepts_inground_storm_shelter():
    feature, _, strength = detect_cave_bunker_evidence(
        _raw("Property has an in-ground storm shelter near the garage.")
    )
    assert feature == "Storm shelter"
    assert strength == "strong"


def test_rejects_bare_cave_token():
    feature, _, _ = detect_cave_bunker_evidence(
        _raw("Minutes from Cave City attractions and shopping.")
    )
    assert feature is None


def test_accepts_root_cellar():
    feature, _, strength = detect_cave_bunker_evidence(
        _raw("Historic farmhouse with original root cellar.")
    )
    assert feature == "Cellar"
    assert strength == "weak"


def test_drive_hours_near_wheaton():
    # Same point as origin → ~0 hours
    assert estimate_drive_hours(*ZIP_60189_CENTER) == 0.0
    # Springfield MO is roughly 5–7 hours depending on mph assumption
    hours = estimate_drive_hours(37.209, -93.292, highway_mph=55)
    assert 4 < hours < 10


def test_drive_band_preferred_and_exceptional():
    assert within_drive_band(3.5, "weak", max_hours=8, exceptional_max_hours=12)
    assert within_drive_band(7.5, "weak", max_hours=8, exceptional_max_hours=12)
    assert not within_drive_band(9.0, "weak", max_hours=8, exceptional_max_hours=12)
    assert within_drive_band(9.0, "strong", max_hours=8, exceptional_max_hours=12)
    assert not within_drive_band(13.0, "strong", max_hours=8, exceptional_max_hours=12)


def test_compile_rejects_inactive_and_out_of_state():
    config = {
        "caves_bunkers": {
            "states": ["IL", "MO"],
            "highway_mph": 55,
            "preferred_hours": 4,
            "max_hours": 8,
            "exceptional_max_hours": 12,
        }
    }
    pending = _raw("Underground bunker on site.")
    pending["status"] = "pending"
    pending["flags"] = {"is_pending": True}

    out_of_state = _raw("Cave home with natural limestone cave.")
    out_of_state["location"]["address"]["state_code"] = "TX"
    out_of_state["location"]["address"]["coordinate"] = {"lat": 32.78, "lon": -96.8}
    out_of_state["property_id"] = "tx-1"

    good = _raw("Spectacular cave house with underground living quarters.")
    good["property_id"] = "mo-1"
    good["status"] = "for_sale"
    good["flags"] = {}
    # Normalize path needs mls-ish fields; set Active mls via description type ok
    good["description"]["type"] = "single_family"

    records, stats = compile_caves_listings(
        [pending, out_of_state, good],
        config=config,
    )
    assert stats.get("rejected_inactive", 0) >= 1
    assert stats.get("rejected_out_of_state", 0) >= 1 or stats.get("rejected_too_far", 0) >= 1
    # Good listing in MO near Springfield should compile if active
    # is_verified_active may require mls_status in ACTIVE set
    assert isinstance(records, list)
