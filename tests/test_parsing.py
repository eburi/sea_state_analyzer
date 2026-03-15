"""Tests for Signal K delta parsing and self-path filtering."""

from __future__ import annotations

import sys
import os
import pytest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from config import Config
from models import SignalKValueUpdate
from signalk_client import SignalKClient, _parse_sk_timestamp, _extract_source_label
from state_store import SelfStateStore
from paths import ATTITUDE_ROLL, ATTITUDE


# --------------------------------------------------------------------------- #
# Timestamp parsing                                                            #
# --------------------------------------------------------------------------- #


def test_parse_sk_timestamp_utc_z():
    ts = _parse_sk_timestamp("2024-06-01T12:00:00.000Z")
    assert ts is not None
    assert ts.tzinfo is not None
    assert ts.year == 2024
    assert ts.hour == 12


def test_parse_sk_timestamp_offset():
    ts = _parse_sk_timestamp("2024-06-01T14:00:00+02:00")
    assert ts is not None
    assert ts.tzinfo is not None


def test_parse_sk_timestamp_none():
    assert _parse_sk_timestamp(None) is None
    assert _parse_sk_timestamp("") is None
    assert _parse_sk_timestamp("not-a-date") is None


# --------------------------------------------------------------------------- #
# Source label extraction                                                      #
# --------------------------------------------------------------------------- #


def test_extract_source_label_dollar_source():
    block = {"$source": "my.sensor", "values": []}
    assert _extract_source_label(block) == "my.sensor"


def test_extract_source_label_source_dict():
    block = {"source": {"label": "GPS", "type": "NMEA0183"}, "values": []}
    assert _extract_source_label(block) == "GPS"


def test_extract_source_label_missing():
    block = {"values": []}
    assert _extract_source_label(block) is None


# --------------------------------------------------------------------------- #
# Self context filtering                                                       #
# --------------------------------------------------------------------------- #


def test_self_filter_vessels_self():
    config = Config()
    client = SignalKClient(config)
    assert client._is_self("vessels.self") is True


def test_self_filter_urn_after_hello():
    config = Config()
    client = SignalKClient(config)
    # Simulate hello setting a URN context
    client._self_context = "vessels.urn:mrn:imo:mmsi:123456789"
    assert client._is_self("vessels.urn:mrn:imo:mmsi:123456789") is True
    assert client._is_self("vessels.urn:mrn:imo:mmsi:999999999") is False


def test_self_filter_other_vessel():
    config = Config()
    client = SignalKClient(config)
    assert client._is_self("vessels.urn:mrn:imo:mmsi:999") is False


# --------------------------------------------------------------------------- #
# State store: delta merging                                                    #
# --------------------------------------------------------------------------- #


def _make_update(path: str, value, received_at=None) -> SignalKValueUpdate:
    if received_at is None:
        received_at = datetime.now(timezone.utc)
    return SignalKValueUpdate(
        path=path,
        value=value,
        source="test",
        timestamp=received_at,
        received_at=received_at,
    )


def test_state_store_scalar():
    config = Config()
    store = SelfStateStore(config)
    store.apply_update_sync(_make_update(ATTITUDE_ROLL, 0.15))
    snap = store.snapshot()
    assert snap.roll == pytest.approx(0.15)


def test_state_store_compound_attitude():
    config = Config()
    store = SelfStateStore(config)
    # Compound object update
    compound = {"roll": 0.10, "pitch": -0.05, "yaw": 1.23}
    store.apply_update_sync(_make_update(ATTITUDE, compound))
    snap = store.snapshot()
    assert snap.roll == pytest.approx(0.10)
    assert snap.pitch == pytest.approx(-0.05)
    assert snap.yaw == pytest.approx(1.23)


def test_state_store_partial_compound():
    """Partial compound attitude update should only overwrite specified subkeys."""
    config = Config()
    store = SelfStateStore(config)
    store.apply_update_sync(_make_update(ATTITUDE_ROLL, 0.20))
    store.apply_update_sync(_make_update(ATTITUDE, {"pitch": 0.05}))
    snap = store.snapshot()
    # roll from previous scalar update should still be there
    assert snap.roll == pytest.approx(0.20)
    assert snap.pitch == pytest.approx(0.05)


def test_state_store_none_value_ignored():
    config = Config()
    store = SelfStateStore(config)
    store.apply_update_sync(_make_update(ATTITUDE_ROLL, 0.30))
    store.apply_update_sync(_make_update(ATTITUDE_ROLL, None))
    snap = store.snapshot()
    # None update should not overwrite existing value
    assert snap.roll == pytest.approx(0.30)


def test_state_store_freshness():
    import time

    config = Config(stale_threshold_s=1.0)
    store = SelfStateStore(config)
    store.apply_update_sync(_make_update(ATTITUDE_ROLL, 0.10))
    snap = store.snapshot()
    assert snap.field_valid["roll"] is True

    time.sleep(1.1)
    snap2 = store.snapshot()
    assert snap2.field_valid["roll"] is False


def test_state_store_position():
    config = Config()
    store = SelfStateStore(config)
    from paths import POSITION

    pos = {"latitude": 51.5, "longitude": -0.1}
    store.apply_update_sync(_make_update(POSITION, pos))
    snap = store.snapshot()
    assert snap.latitude == pytest.approx(51.5)
    assert snap.longitude == pytest.approx(-0.1)
