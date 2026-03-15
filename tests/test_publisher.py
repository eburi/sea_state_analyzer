"""Tests for Signal K delta publisher.

Tests cover:
- MotionEstimate to delta value conversion
- Delta message building and JSON formatting
- Edge cases: empty estimates, None fields, string values
- Async publish via mock WebSocket
- Config integration (publish_to_signalk env var)
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import MotionEstimate
from signalk_publisher import (
    _motion_estimate_to_values,
    build_delta_message,
    build_meta_delta,
    publish_delta,
)
from paths import (
    WAVE_COMFORT_PROXY,
    WAVE_ENCOUNTER_DIRECTION,
    WAVE_ENCOUNTER_PERIOD,
    WAVE_MOTION_REGIME,
    WAVE_MOTION_SEVERITY,
    WAVE_PATH_META,
    WAVE_PERIOD,
    WAVE_PERIOD_CONFIDENCE,
    WAVE_SIGNIFICANT_HEIGHT,
    WAVE_SWELL_1_CONFIDENCE,
    WAVE_SWELL_1_HEIGHT,
    WAVE_SWELL_1_PERIOD,
    WAVE_SWELL_2_CONFIDENCE,
    WAVE_SWELL_2_HEIGHT,
    WAVE_SWELL_2_PERIOD,
    WAVE_TRUE_PERIOD,
    WAVE_TRUE_WAVELENGTH,
    WAVE_WIND_WAVE_CONFIDENCE,
    WAVE_WIND_WAVE_HEIGHT,
    WAVE_WIND_WAVE_PERIOD,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

def _make_estimate(**overrides: Any) -> MotionEstimate:
    """Create a MotionEstimate with sensible defaults for testing."""
    defaults = dict(
        timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        window_s=60.0,
        motion_severity=0.42,
        motion_severity_smoothed=0.40,
        motion_regime="moderate",
        dominant_roll_period=5.2,
        dominant_pitch_period=4.8,
        encounter_period_estimate=5.0,
        period_confidence=0.75,
        true_wave_period=6.1,
        true_wavelength=58.0,
        wave_speed=9.5,
        doppler_delta_v=1.2,
        doppler_correction_valid=True,
        encounter_direction="beam_like",
        direction_confidence=0.65,
        roll_dominant=True,
        motion_regularity="regular",
        confusion_index=0.2,
        comfort_proxy=0.35,
        severity_trend="stable",
        overall_confidence=0.70,
    )
    defaults.update(overrides)
    return MotionEstimate(**defaults)


# --------------------------------------------------------------------------- #
# Value extraction tests                                                       #
# --------------------------------------------------------------------------- #

class TestMotionEstimateToValues:
    def test_full_estimate_produces_values(self) -> None:
        me = _make_estimate()
        values = _motion_estimate_to_values(me)
        assert len(values) > 0
        paths = [v["path"] for v in values]
        assert WAVE_MOTION_SEVERITY in paths
        assert WAVE_MOTION_REGIME in paths
        assert WAVE_ENCOUNTER_PERIOD in paths
        assert WAVE_PERIOD in paths
        assert WAVE_TRUE_PERIOD in paths
        assert WAVE_TRUE_WAVELENGTH in paths
        assert WAVE_ENCOUNTER_DIRECTION in paths
        assert WAVE_PERIOD_CONFIDENCE in paths
        assert WAVE_COMFORT_PROXY in paths

    def test_severity_uses_smoothed_when_available(self) -> None:
        me = _make_estimate(motion_severity=0.50, motion_severity_smoothed=0.42)
        values = _motion_estimate_to_values(me)
        sev = next(v for v in values if v["path"] == WAVE_MOTION_SEVERITY)
        assert sev["value"] == 0.42  # smoothed, not raw

    def test_severity_falls_back_to_raw(self) -> None:
        me = _make_estimate(motion_severity=0.50, motion_severity_smoothed=None)
        values = _motion_estimate_to_values(me)
        sev = next(v for v in values if v["path"] == WAVE_MOTION_SEVERITY)
        assert sev["value"] == 0.5

    def test_empty_estimate_produces_no_values(self) -> None:
        me = MotionEstimate(
            timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            window_s=60.0,
        )
        values = _motion_estimate_to_values(me)
        assert values == []

    def test_partial_estimate_omits_none_fields(self) -> None:
        me = _make_estimate(
            true_wave_period=None,
            true_wavelength=None,
            comfort_proxy=None,
            encounter_direction=None,
        )
        values = _motion_estimate_to_values(me)
        paths = [v["path"] for v in values]
        assert WAVE_TRUE_PERIOD not in paths
        assert WAVE_TRUE_WAVELENGTH not in paths
        assert WAVE_COMFORT_PROXY not in paths
        assert WAVE_ENCOUNTER_DIRECTION not in paths
        # But severity and regime should still be present
        assert WAVE_MOTION_SEVERITY in paths
        assert WAVE_MOTION_REGIME in paths

    def test_doppler_invalid_suppresses_true_period(self) -> None:
        me = _make_estimate(
            true_wave_period=6.1,
            true_wavelength=58.0,
            doppler_correction_valid=False,
        )
        values = _motion_estimate_to_values(me)
        paths = [v["path"] for v in values]
        assert WAVE_TRUE_PERIOD not in paths
        assert WAVE_TRUE_WAVELENGTH not in paths

    def test_regime_is_string_value(self) -> None:
        me = _make_estimate(motion_regime="heavy")
        values = _motion_estimate_to_values(me)
        regime = next(v for v in values if v["path"] == WAVE_MOTION_REGIME)
        assert regime["value"] == "heavy"
        assert isinstance(regime["value"], str)

    def test_encounter_direction_is_string(self) -> None:
        me = _make_estimate(encounter_direction="head_or_following_like")
        values = _motion_estimate_to_values(me)
        d = next(v for v in values if v["path"] == WAVE_ENCOUNTER_DIRECTION)
        assert d["value"] == "head_or_following_like"

    def test_values_are_rounded(self) -> None:
        me = _make_estimate(
            motion_severity_smoothed=0.123456789,
            encounter_period_estimate=5.6789,
            period_confidence=0.7777,
            comfort_proxy=0.123456,
        )
        values = _motion_estimate_to_values(me)
        by_path = {v["path"]: v["value"] for v in values}
        assert by_path[WAVE_MOTION_SEVERITY] == 0.123
        assert by_path[WAVE_ENCOUNTER_PERIOD] == 5.68
        assert by_path[WAVE_PERIOD_CONFIDENCE] == 0.78
        assert by_path[WAVE_COMFORT_PROXY] == 0.123

    def test_encounter_period_published_as_both_paths(self) -> None:
        """encounter_period_estimate should publish to both ENCOUNTER_PERIOD
        and the primary WAVE_PERIOD path."""
        me = _make_estimate(encounter_period_estimate=7.3)
        values = _motion_estimate_to_values(me)
        paths = [v["path"] for v in values]
        assert WAVE_ENCOUNTER_PERIOD in paths
        assert WAVE_PERIOD in paths
        enc = next(v for v in values if v["path"] == WAVE_ENCOUNTER_PERIOD)
        per = next(v for v in values if v["path"] == WAVE_PERIOD)
        assert enc["value"] == per["value"] == 7.3

    def test_wind_wave_partition_published(self) -> None:
        me = _make_estimate(
            wind_wave_height=1.2,
            wind_wave_period=5.5,
            wind_wave_confidence=0.78,
        )
        values = _motion_estimate_to_values(me)
        paths = [v["path"] for v in values]
        assert WAVE_WIND_WAVE_HEIGHT in paths
        assert WAVE_WIND_WAVE_PERIOD in paths
        assert WAVE_WIND_WAVE_CONFIDENCE in paths
        ht = next(v for v in values if v["path"] == WAVE_WIND_WAVE_HEIGHT)
        assert ht["value"] == 1.2

    def test_swell_1_partition_published(self) -> None:
        me = _make_estimate(
            swell_1_height=0.8,
            swell_1_period=9.3,
            swell_1_confidence=0.65,
        )
        values = _motion_estimate_to_values(me)
        paths = [v["path"] for v in values]
        assert WAVE_SWELL_1_HEIGHT in paths
        assert WAVE_SWELL_1_PERIOD in paths
        assert WAVE_SWELL_1_CONFIDENCE in paths
        tp = next(v for v in values if v["path"] == WAVE_SWELL_1_PERIOD)
        assert tp["value"] == 9.3

    def test_swell_2_partition_published(self) -> None:
        me = _make_estimate(
            swell_2_height=0.5,
            swell_2_period=14.1,
            swell_2_confidence=0.42,
        )
        values = _motion_estimate_to_values(me)
        paths = [v["path"] for v in values]
        assert WAVE_SWELL_2_HEIGHT in paths
        assert WAVE_SWELL_2_PERIOD in paths
        assert WAVE_SWELL_2_CONFIDENCE in paths

    def test_partition_none_omitted(self) -> None:
        """Partition fields that are None should not appear in output."""
        me = _make_estimate(
            wind_wave_height=1.0,
            wind_wave_period=None,
            wind_wave_confidence=None,
            swell_1_height=None,
        )
        values = _motion_estimate_to_values(me)
        paths = [v["path"] for v in values]
        assert WAVE_WIND_WAVE_HEIGHT in paths
        assert WAVE_WIND_WAVE_PERIOD not in paths
        assert WAVE_WIND_WAVE_CONFIDENCE not in paths
        assert WAVE_SWELL_1_HEIGHT not in paths

    def test_partition_rounding(self) -> None:
        me = _make_estimate(
            wind_wave_height=1.234,
            wind_wave_period=5.678,
            wind_wave_confidence=0.789,
        )
        values = _motion_estimate_to_values(me)
        by_path = {v["path"]: v["value"] for v in values}
        assert by_path[WAVE_WIND_WAVE_HEIGHT] == 1.23   # 2 decimal places
        assert by_path[WAVE_WIND_WAVE_PERIOD] == 5.7    # 1 decimal place
        assert by_path[WAVE_WIND_WAVE_CONFIDENCE] == 0.79  # 2 decimal places


# --------------------------------------------------------------------------- #
# Delta message building tests                                                 #
# --------------------------------------------------------------------------- #

class TestBuildDeltaMessage:
    def test_returns_valid_json(self) -> None:
        me = _make_estimate()
        msg = build_delta_message(me)
        assert msg is not None
        parsed = json.loads(msg)
        assert "context" in parsed
        assert "updates" in parsed

    def test_default_context_is_vessels_self(self) -> None:
        me = _make_estimate()
        msg = build_delta_message(me)
        parsed = json.loads(msg)
        assert parsed["context"] == "vessels.self"

    def test_custom_context(self) -> None:
        me = _make_estimate()
        msg = build_delta_message(me, self_context="vessels.urn:mrn:imo:mmsi:538071881")
        parsed = json.loads(msg)
        assert parsed["context"] == "vessels.urn:mrn:imo:mmsi:538071881"

    def test_source_label(self) -> None:
        me = _make_estimate()
        msg = build_delta_message(me, source_label="test_source")
        parsed = json.loads(msg)
        source = parsed["updates"][0]["source"]
        assert source["label"] == "test_source"
        assert source["type"] == "signalk"

    def test_default_source_label(self) -> None:
        me = _make_estimate()
        msg = build_delta_message(me)
        parsed = json.loads(msg)
        assert parsed["updates"][0]["source"]["label"] == "boat_wave_state"

    def test_timestamp_in_iso_format(self) -> None:
        me = _make_estimate(
            timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        )
        msg = build_delta_message(me)
        parsed = json.loads(msg)
        ts = parsed["updates"][0]["timestamp"]
        assert ts == "2024-06-01T12:00:00Z"

    def test_values_array_has_correct_structure(self) -> None:
        me = _make_estimate()
        msg = build_delta_message(me)
        parsed = json.loads(msg)
        values = parsed["updates"][0]["values"]
        assert isinstance(values, list)
        for v in values:
            assert "path" in v
            assert "value" in v
            assert isinstance(v["path"], str)

    def test_empty_estimate_returns_none(self) -> None:
        me = MotionEstimate(
            timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            window_s=60.0,
        )
        msg = build_delta_message(me)
        assert msg is None

    def test_compact_json(self) -> None:
        """Output should use compact separators (no spaces)."""
        me = _make_estimate()
        msg = build_delta_message(me)
        assert msg is not None
        # No space after : or , in compact JSON
        assert ": " not in msg
        assert ", " not in msg


# --------------------------------------------------------------------------- #
# Async publish tests                                                          #
# --------------------------------------------------------------------------- #

class TestPublishDelta:
    @pytest.fixture
    def mock_ws(self) -> AsyncMock:
        ws = AsyncMock()
        ws.send = AsyncMock(return_value=None)
        return ws

    @pytest.mark.asyncio
    async def test_publish_sends_message(self, mock_ws: AsyncMock) -> None:
        me = _make_estimate()
        ok = await publish_delta(mock_ws, me)
        assert ok is True
        mock_ws.send.assert_called_once()
        # Verify sent JSON is valid
        sent = mock_ws.send.call_args[0][0]
        parsed = json.loads(sent)
        assert parsed["context"] == "vessels.self"

    @pytest.mark.asyncio
    async def test_publish_returns_false_on_empty(self, mock_ws: AsyncMock) -> None:
        me = MotionEstimate(
            timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            window_s=60.0,
        )
        ok = await publish_delta(mock_ws, me)
        assert ok is False
        mock_ws.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_publish_returns_false_on_send_error(self, mock_ws: AsyncMock) -> None:
        mock_ws.send.side_effect = ConnectionError("Connection lost")
        me = _make_estimate()
        ok = await publish_delta(mock_ws, me)
        assert ok is False

    @pytest.mark.asyncio
    async def test_publish_custom_context(self, mock_ws: AsyncMock) -> None:
        me = _make_estimate()
        await publish_delta(
            mock_ws, me,
            self_context="vessels.urn:mrn:imo:mmsi:538071881",
            source_label="custom_source",
        )
        sent = mock_ws.send.call_args[0][0]
        parsed = json.loads(sent)
        assert parsed["context"] == "vessels.urn:mrn:imo:mmsi:538071881"
        assert parsed["updates"][0]["source"]["label"] == "custom_source"


# --------------------------------------------------------------------------- #
# Config integration tests                                                     #
# --------------------------------------------------------------------------- #

class TestConfigPublish:
    def test_default_publish_enabled(self) -> None:
        from config import Config
        c = Config()
        assert c.publish_to_signalk is True

    def test_publish_disableable(self) -> None:
        from config import Config
        c = Config(publish_to_signalk=False)
        assert c.publish_to_signalk is False

    def test_default_publish_interval(self) -> None:
        from config import Config
        c = Config()
        assert c.publish_interval_s == 5.0

    def test_default_source_label(self) -> None:
        from config import Config
        c = Config()
        assert c.publish_source_label == "boat_wave_state"

    def test_from_env_publish_to_signalk(self) -> None:
        import os
        os.environ["BOAT_STATE_PUBLISH_TO_SIGNALK"] = "false"
        try:
            from config import Config
            c = Config.from_env()
            assert c.publish_to_signalk is False
        finally:
            del os.environ["BOAT_STATE_PUBLISH_TO_SIGNALK"]


# --------------------------------------------------------------------------- #
# SignalKClient.send() tests                                                   #
# --------------------------------------------------------------------------- #

class TestSignalKClientSend:
    @pytest.mark.asyncio
    async def test_send_when_not_connected(self) -> None:
        from config import Config
        from signalk_client import SignalKClient
        client = SignalKClient(Config())
        ok = await client.send('{"test": true}')
        assert ok is False

    @pytest.mark.asyncio
    async def test_send_when_connected(self) -> None:
        from config import Config
        from signalk_client import SignalKClient
        client = SignalKClient(Config())
        client._connected = True
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        client._ws = mock_ws
        ok = await client.send('{"test": true}')
        assert ok is True
        mock_ws.send.assert_called_once_with('{"test": true}')

    @pytest.mark.asyncio
    async def test_send_handles_exception(self) -> None:
        from config import Config
        from signalk_client import SignalKClient
        client = SignalKClient(Config())
        client._connected = True
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=ConnectionError("broken"))
        client._ws = mock_ws
        ok = await client.send('{"test": true}')
        assert ok is False


# --------------------------------------------------------------------------- #
# Meta delta tests                                                             #
# --------------------------------------------------------------------------- #

class TestBuildMetaDelta:
    def test_returns_valid_json(self) -> None:
        msg = build_meta_delta()
        parsed = json.loads(msg)
        assert "context" in parsed
        assert "updates" in parsed

    def test_default_context_is_vessels_self(self) -> None:
        msg = build_meta_delta()
        parsed = json.loads(msg)
        assert parsed["context"] == "vessels.self"

    def test_custom_context(self) -> None:
        msg = build_meta_delta(self_context="vessels.urn:mrn:imo:mmsi:538071881")
        parsed = json.loads(msg)
        assert parsed["context"] == "vessels.urn:mrn:imo:mmsi:538071881"

    def test_uses_meta_key_not_values(self) -> None:
        """Meta deltas use 'meta' instead of 'values' in the update block."""
        msg = build_meta_delta()
        parsed = json.loads(msg)
        update = parsed["updates"][0]
        assert "meta" in update
        assert "values" not in update

    def test_meta_entries_have_path_and_value(self) -> None:
        msg = build_meta_delta()
        parsed = json.loads(msg)
        meta = parsed["updates"][0]["meta"]
        assert isinstance(meta, list)
        assert len(meta) > 0
        for entry in meta:
            assert "path" in entry
            assert "value" in entry
            assert isinstance(entry["path"], str)
            assert isinstance(entry["value"], dict)

    def test_covers_all_wave_path_meta_entries(self) -> None:
        """Every path in WAVE_PATH_META should appear in the meta delta."""
        msg = build_meta_delta()
        parsed = json.loads(msg)
        meta = parsed["updates"][0]["meta"]
        paths = {entry["path"] for entry in meta}
        for path in WAVE_PATH_META:
            assert path in paths, f"Missing meta for {path}"

    def test_significant_height_has_units(self) -> None:
        msg = build_meta_delta()
        parsed = json.loads(msg)
        meta = parsed["updates"][0]["meta"]
        hs = next(e for e in meta if e["path"] == WAVE_SIGNIFICANT_HEIGHT)
        assert hs["value"]["units"] == "m"
        assert "description" in hs["value"]
        assert "displayName" in hs["value"]

    def test_motion_severity_has_display_scale(self) -> None:
        msg = build_meta_delta()
        parsed = json.loads(msg)
        meta = parsed["updates"][0]["meta"]
        from paths import WAVE_MOTION_SEVERITY
        sev = next(e for e in meta if e["path"] == WAVE_MOTION_SEVERITY)
        assert sev["value"]["units"] == "ratio"
        assert "displayScale" in sev["value"]
        scale = sev["value"]["displayScale"]
        assert scale["lower"] == 0
        assert scale["upper"] == 1

    def test_motion_regime_has_enum(self) -> None:
        msg = build_meta_delta()
        parsed = json.loads(msg)
        meta = parsed["updates"][0]["meta"]
        from paths import WAVE_MOTION_REGIME
        regime = next(e for e in meta if e["path"] == WAVE_MOTION_REGIME)
        assert "enum" in regime["value"]
        assert "calm" in regime["value"]["enum"]
        assert "heavy" in regime["value"]["enum"]

    def test_encounter_direction_has_enum(self) -> None:
        msg = build_meta_delta()
        parsed = json.loads(msg)
        meta = parsed["updates"][0]["meta"]
        from paths import WAVE_ENCOUNTER_DIRECTION
        direction = next(e for e in meta if e["path"] == WAVE_ENCOUNTER_DIRECTION)
        assert "enum" in direction["value"]
        assert "beam_like" in direction["value"]["enum"]

    def test_compact_json(self) -> None:
        """Output should use compact separators (no extra whitespace
        between JSON tokens).  Note: description strings may contain
        ', ' naturally, so we parse and re-serialize to verify."""
        msg = build_meta_delta()
        parsed = json.loads(msg)
        re_compact = json.dumps(parsed, separators=(",", ":"))
        assert msg == re_compact

    def test_no_source_or_timestamp_in_meta_update(self) -> None:
        """Meta updates don't need source or timestamp."""
        msg = build_meta_delta()
        parsed = json.loads(msg)
        update = parsed["updates"][0]
        assert "source" not in update
        assert "timestamp" not in update

    def test_meta_values_are_dicts_not_references(self) -> None:
        """Meta values should be independent dicts (not shared references
        with WAVE_PATH_META)."""
        msg = build_meta_delta()
        parsed = json.loads(msg)
        meta = parsed["updates"][0]["meta"]
        for entry in meta:
            path = entry["path"]
            # Mutating the parsed output should not affect the source dict
            entry["value"]["_test_key"] = True
            assert "_test_key" not in WAVE_PATH_META[path]

    def test_partition_paths_have_meta(self) -> None:
        """All 9 partition paths must have meta entries."""
        msg = build_meta_delta()
        parsed = json.loads(msg)
        meta = parsed["updates"][0]["meta"]
        paths = {e["path"] for e in meta}
        for p in [
            WAVE_WIND_WAVE_HEIGHT, WAVE_WIND_WAVE_PERIOD, WAVE_WIND_WAVE_CONFIDENCE,
            WAVE_SWELL_1_HEIGHT, WAVE_SWELL_1_PERIOD, WAVE_SWELL_1_CONFIDENCE,
            WAVE_SWELL_2_HEIGHT, WAVE_SWELL_2_PERIOD, WAVE_SWELL_2_CONFIDENCE,
        ]:
            assert p in paths, f"Missing meta for partition path {p}"

    def test_partition_height_meta_has_units_m(self) -> None:
        """All partition height paths should have units 'm'."""
        msg = build_meta_delta()
        parsed = json.loads(msg)
        meta = parsed["updates"][0]["meta"]
        for path in [WAVE_WIND_WAVE_HEIGHT, WAVE_SWELL_1_HEIGHT, WAVE_SWELL_2_HEIGHT]:
            entry = next(e for e in meta if e["path"] == path)
            assert entry["value"]["units"] == "m"

    def test_partition_period_meta_has_units_s(self) -> None:
        """All partition period paths should have units 's'."""
        msg = build_meta_delta()
        parsed = json.loads(msg)
        meta = parsed["updates"][0]["meta"]
        for path in [WAVE_WIND_WAVE_PERIOD, WAVE_SWELL_1_PERIOD, WAVE_SWELL_2_PERIOD]:
            entry = next(e for e in meta if e["path"] == path)
            assert entry["value"]["units"] == "s"
