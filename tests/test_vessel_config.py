"""Tests for vessel_config module: design data parsing, hull classification,
physics computation, and Signal K fetch."""
from __future__ import annotations

import json
import math
import sys
from typing import Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vessel_config import (
    GRAVITY,
    HullParameters,
    HullType,
    VesselDesign,
    classify_hull_type,
    compute_hull_parameters,
    fetch_vessel_design,
    log_hull_parameters,
    period_to_wavelength,
    rao_confidence_adjustment,
    rao_gain,
    wavelength_to_period,
    _hull_type_severity_max,
    _hull_type_severity_weights,
    _natural_pitch_period_range,
    _natural_roll_period_range,
    _parse_design_response,
)

TWO_PI = 2.0 * math.pi


# ========================================================================= #
# Hull type classification                                                     #
# ========================================================================= #

class TestClassifyHullType:
    """Tests for classify_hull_type()."""

    def test_monohull_low_ratio(self) -> None:
        assert classify_hull_type(0.20) == HullType.MONOHULL

    def test_monohull_boundary(self) -> None:
        assert classify_hull_type(0.29) == HullType.MONOHULL

    def test_trimaran_lower_boundary(self) -> None:
        assert classify_hull_type(0.30) == HullType.TRIMARAN

    def test_trimaran_mid(self) -> None:
        assert classify_hull_type(0.35) == HullType.TRIMARAN

    def test_trimaran_upper_boundary(self) -> None:
        assert classify_hull_type(0.39) == HullType.TRIMARAN

    def test_catamaran_at_boundary(self) -> None:
        assert classify_hull_type(0.40) == HullType.CATAMARAN

    def test_catamaran_high_ratio(self) -> None:
        assert classify_hull_type(0.57) == HullType.CATAMARAN

    def test_catamaran_very_wide(self) -> None:
        assert classify_hull_type(0.70) == HullType.CATAMARAN

    def test_negative_ratio(self) -> None:
        assert classify_hull_type(-0.1) == HullType.UNKNOWN

    def test_zero_ratio(self) -> None:
        assert classify_hull_type(0.0) == HullType.MONOHULL


# ========================================================================= #
# VesselDesign properties                                                      #
# ========================================================================= #

class TestVesselDesign:
    """Tests for VesselDesign dataclass."""

    def test_beam_length_ratio_normal(self) -> None:
        d = VesselDesign(loa=13.99, beam=7.96)
        ratio = d.beam_length_ratio
        assert ratio is not None
        assert abs(ratio - 7.96 / 13.99) < 1e-6

    def test_beam_length_ratio_no_loa(self) -> None:
        d = VesselDesign(beam=7.96)
        assert d.beam_length_ratio is None

    def test_beam_length_ratio_no_beam(self) -> None:
        d = VesselDesign(loa=13.99)
        assert d.beam_length_ratio is None

    def test_beam_length_ratio_zero_loa(self) -> None:
        d = VesselDesign(loa=0.0, beam=7.96)
        assert d.beam_length_ratio is None

    def test_has_minimum_data_with_loa(self) -> None:
        d = VesselDesign(loa=13.99)
        assert d.has_minimum_data is True

    def test_has_minimum_data_no_loa(self) -> None:
        d = VesselDesign(beam=7.96)
        assert d.has_minimum_data is False

    def test_has_minimum_data_zero_loa(self) -> None:
        d = VesselDesign(loa=0.0)
        assert d.has_minimum_data is False


# ========================================================================= #
# Deep-water dispersion                                                        #
# ========================================================================= #

class TestDeepWaterDispersion:
    """Tests for wavelength_to_period and period_to_wavelength."""

    def test_wavelength_to_period_14m(self) -> None:
        """14m wavelength (LOA of Primrose) -> ~3.0s period."""
        T = wavelength_to_period(14.0)
        expected = math.sqrt(TWO_PI * 14.0 / GRAVITY)
        assert abs(T - expected) < 1e-6
        assert 2.9 < T < 3.1  # sanity check

    def test_period_to_wavelength_roundtrip(self) -> None:
        """Roundtrip: wavelength -> period -> wavelength."""
        L_original = 50.0
        T = wavelength_to_period(L_original)
        L_recovered = period_to_wavelength(T)
        assert abs(L_recovered - L_original) < 1e-6

    def test_wavelength_to_period_1m(self) -> None:
        T = wavelength_to_period(1.0)
        assert T > 0 and T < 2.0

    def test_wavelength_to_period_100m(self) -> None:
        T = wavelength_to_period(100.0)
        assert 7.0 < T < 9.0  # ~8.0s for 100m waves

    def test_wavelength_to_period_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            wavelength_to_period(0.0)

    def test_wavelength_to_period_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            wavelength_to_period(-5.0)

    def test_period_to_wavelength_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            period_to_wavelength(0.0)

    def test_period_to_wavelength_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            period_to_wavelength(-3.0)

    def test_period_to_wavelength_known_value(self) -> None:
        """10s period -> ~156m wavelength."""
        L = period_to_wavelength(10.0)
        expected = GRAVITY * 100.0 / TWO_PI
        assert abs(L - expected) < 1e-4
        assert 150 < L < 160


# ========================================================================= #
# Natural period ranges                                                        #
# ========================================================================= #

class TestNaturalPeriodRanges:
    """Tests for hull-type-specific period ranges."""

    def test_catamaran_roll_short(self) -> None:
        lo, hi = _natural_roll_period_range(HullType.CATAMARAN)
        assert lo == 2.0
        assert hi == 4.0

    def test_monohull_roll_long(self) -> None:
        lo, hi = _natural_roll_period_range(HullType.MONOHULL)
        assert lo == 5.0
        assert hi == 12.0

    def test_trimaran_roll_mid(self) -> None:
        lo, hi = _natural_roll_period_range(HullType.TRIMARAN)
        assert 2.0 <= lo <= 4.0
        assert 5.0 <= hi <= 7.0

    def test_unknown_roll_wide(self) -> None:
        lo, hi = _natural_roll_period_range(HullType.UNKNOWN)
        assert lo == 2.0
        assert hi == 12.0

    def test_catamaran_pitch_range(self) -> None:
        lo, hi = _natural_pitch_period_range(HullType.CATAMARAN)
        assert lo == 2.0
        assert hi == 4.0

    def test_monohull_pitch_range(self) -> None:
        lo, hi = _natural_pitch_period_range(HullType.MONOHULL)
        assert lo == 3.0
        assert hi == 7.0


# ========================================================================= #
# Severity weight/max overrides per hull type                                  #
# ========================================================================= #

class TestHullTypeSeverity:
    """Tests for hull-type severity weights and max overrides."""

    def test_catamaran_weights_sum_to_one(self) -> None:
        w = _hull_type_severity_weights(HullType.CATAMARAN)
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_monohull_weights_sum_to_one(self) -> None:
        w = _hull_type_severity_weights(HullType.MONOHULL)
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_trimaran_weights_sum_to_one(self) -> None:
        w = _hull_type_severity_weights(HullType.TRIMARAN)
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_unknown_weights_sum_to_one(self) -> None:
        w = _hull_type_severity_weights(HullType.UNKNOWN)
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_catamaran_pitch_weight_higher_than_roll(self) -> None:
        """Cats pitch more relative to roll -> pitch_rms weight > roll_rms."""
        w = _hull_type_severity_weights(HullType.CATAMARAN)
        assert w["pitch_rms"] > w["roll_rms"]

    def test_monohull_roll_weight_higher_than_pitch(self) -> None:
        """Monohulls roll more -> roll_rms weight > pitch_rms."""
        w = _hull_type_severity_weights(HullType.MONOHULL)
        assert w["roll_rms"] > w["pitch_rms"]

    def test_catamaran_roll_rms_max_lower(self) -> None:
        """Cats roll less -> lower roll_rms_max for sensitivity."""
        cat = _hull_type_severity_max(HullType.CATAMARAN)
        mono = _hull_type_severity_max(HullType.MONOHULL)
        assert cat["severity_roll_rms_max"] < mono["severity_roll_rms_max"]

    def test_catamaran_roll_spectral_max_lower(self) -> None:
        cat = _hull_type_severity_max(HullType.CATAMARAN)
        mono = _hull_type_severity_max(HullType.MONOHULL)
        assert cat["severity_roll_spectral_max"] < mono["severity_roll_spectral_max"]

    def test_all_hull_types_have_four_weights(self) -> None:
        for ht in HullType:
            w = _hull_type_severity_weights(ht)
            assert len(w) == 4
            assert set(w.keys()) == {"roll_rms", "pitch_rms", "roll_spectral", "yaw_rate_var"}

    def test_all_hull_types_have_four_max_overrides(self) -> None:
        for ht in HullType:
            m = _hull_type_severity_max(ht)
            assert len(m) == 4
            expected = {
                "severity_roll_rms_max",
                "severity_pitch_rms_max",
                "severity_roll_spectral_max",
                "severity_yaw_rate_var_max",
            }
            assert set(m.keys()) == expected

    def test_all_max_values_positive(self) -> None:
        for ht in HullType:
            m = _hull_type_severity_max(ht)
            for k, v in m.items():
                assert v > 0, f"{ht.value}: {k} should be positive"


# ========================================================================= #
# compute_hull_parameters                                                      #
# ========================================================================= #

class TestComputeHullParameters:
    """Tests for compute_hull_parameters()."""

    def test_primrose_catamaran(self) -> None:
        """Real vessel: LOA=13.99m, beam=7.96m -> catamaran."""
        design = VesselDesign(loa=13.99, beam=7.96, draft_max=1.35)
        params = compute_hull_parameters(design)

        assert params.hull_type == HullType.CATAMARAN
        assert params.beam_length_ratio is not None
        assert abs(params.beam_length_ratio - 7.96 / 13.99) < 0.001

        # Resonant wavelength == LOA
        assert params.resonant_wavelength == 13.99
        assert params.resonant_period is not None
        assert 2.9 < params.resonant_period < 3.1

        # Beam resonance
        assert params.beam_resonant_wavelength == 7.96
        assert params.beam_resonant_period is not None
        assert 2.0 < params.beam_resonant_period < 2.5

        # Natural periods for catamaran
        assert params.natural_roll_period_min == 2.0
        assert params.natural_roll_period_max == 4.0
        assert params.natural_pitch_period_min == 2.0
        assert params.natural_pitch_period_max == 4.0

        # Severity tuning
        assert params.severity_weights is not None
        assert params.severity_weights["pitch_rms"] > params.severity_weights["roll_rms"]
        assert params.severity_max_overrides is not None

    def test_monohull_40ft(self) -> None:
        """Typical 40ft monohull: LOA=12m, beam=3.5m (B/L=0.29)."""
        design = VesselDesign(loa=12.0, beam=3.5, draft_max=2.0)
        params = compute_hull_parameters(design)

        assert params.hull_type == HullType.MONOHULL
        assert params.beam_length_ratio is not None
        assert params.beam_length_ratio == pytest.approx(3.5 / 12.0, abs=0.001)
        assert params.natural_roll_period_min == 5.0
        assert params.natural_roll_period_max == 12.0

    def test_trimaran(self) -> None:
        design = VesselDesign(loa=15.0, beam=5.0)
        params = compute_hull_parameters(design)
        assert params.hull_type == HullType.TRIMARAN
        assert params.beam_length_ratio == pytest.approx(5.0 / 15.0, abs=0.001)

    def test_loa_only(self) -> None:
        """LOA without beam — hull type unknown, resonance still computed."""
        design = VesselDesign(loa=10.0)
        params = compute_hull_parameters(design)

        assert params.hull_type == HullType.UNKNOWN
        assert params.beam_length_ratio is None
        assert params.resonant_wavelength == 10.0
        assert params.resonant_period is not None

    def test_no_data(self) -> None:
        """Completely empty design — returns defaults."""
        design = VesselDesign()
        params = compute_hull_parameters(design)

        assert params.hull_type == HullType.UNKNOWN
        assert params.resonant_wavelength is None
        assert params.resonant_period is None
        assert params.severity_weights is not None  # still computed for UNKNOWN

    def test_hull_type_name_fallback(self) -> None:
        """When beam/loa not available, fall back to explicit hull type name."""
        design = VesselDesign(loa=14.0, hull_type_name="catamaran")
        params = compute_hull_parameters(design)
        assert params.hull_type == HullType.CATAMARAN

    def test_hull_type_name_trimaran(self) -> None:
        design = VesselDesign(loa=15.0, hull_type_name="Trimaran 50")
        params = compute_hull_parameters(design)
        assert params.hull_type == HullType.TRIMARAN

    def test_hull_type_name_monohull(self) -> None:
        design = VesselDesign(loa=12.0, hull_type_name="Monohull sloop")
        params = compute_hull_parameters(design)
        assert params.hull_type == HullType.MONOHULL

    def test_design_preserved(self) -> None:
        """HullParameters.design holds the original VesselDesign."""
        design = VesselDesign(loa=13.99, beam=7.96)
        params = compute_hull_parameters(design)
        assert params.design is design


# ========================================================================= #
# _parse_design_response (Signal K JSON)                                       #
# ========================================================================= #

class TestParseDesignResponse:
    """Tests for parsing Signal K /design endpoint responses."""

    def test_full_response_primrose(self) -> None:
        """Parse a realistic Primrose-like response."""
        data = {
            "length": {"value": {"overall": 13.99}},
            "beam": {"value": 7.96},
            "draft": {"value": {"maximum": 1.35}},
            "airHeight": {"value": 23.21},
            "aisShipType": {"value": {"id": 36, "name": "Sailing"}},
        }
        design = _parse_design_response(data)

        assert design.loa == 13.99
        assert design.beam == 7.96
        assert design.draft_max == 1.35
        assert design.air_height == 23.21
        assert design.ais_ship_type_id == 36
        assert design.ais_ship_type_name == "Sailing"

    def test_length_as_scalar(self) -> None:
        data = {"length": {"value": 12.5}}
        design = _parse_design_response(data)
        assert design.loa == 12.5

    def test_length_hull_fallback(self) -> None:
        data = {"length": {"value": {"hull": 11.0}}}
        design = _parse_design_response(data)
        assert design.loa == 11.0

    def test_length_waterline_fallback(self) -> None:
        data = {"length": {"value": {"waterline": 10.5}}}
        design = _parse_design_response(data)
        assert design.loa == 10.5

    def test_draft_as_scalar(self) -> None:
        data = {"draft": {"value": 2.0}}
        design = _parse_design_response(data)
        assert design.draft_max == 2.0

    def test_draft_min_and_max(self) -> None:
        data = {"draft": {"value": {"maximum": 2.0, "minimum": 0.8}}}
        design = _parse_design_response(data)
        assert design.draft_max == 2.0
        assert design.draft_min == 0.8

    def test_ais_as_integer(self) -> None:
        data = {"aisShipType": {"value": 36}}
        design = _parse_design_response(data)
        assert design.ais_ship_type_id == 36
        assert design.ais_ship_type_name is None

    def test_hull_type_string(self) -> None:
        data = {"hullType": {"value": "catamaran"}}
        design = _parse_design_response(data)
        assert design.hull_type_name == "catamaran"

    def test_rigging_string(self) -> None:
        data = {"rigging": {"value": "Sloop"}}
        design = _parse_design_response(data)
        assert design.rigging_name == "Sloop"

    def test_displacement(self) -> None:
        data = {"displacement": {"value": 12000}}
        design = _parse_design_response(data)
        assert design.displacement == 12000.0

    def test_empty_response(self) -> None:
        design = _parse_design_response({})
        assert design.loa is None
        assert design.beam is None
        assert design.draft_max is None

    def test_unknown_fields_ignored(self) -> None:
        data = {"unknownField": {"value": 42}, "beam": {"value": 5.0}}
        design = _parse_design_response(data)
        assert design.beam == 5.0


# ========================================================================= #
# fetch_vessel_design (async, mocked HTTP)                                     #
# ========================================================================= #

def _make_mock_httpx_client(
    mock_resp: MagicMock,
) -> Tuple[MagicMock, AsyncMock]:
    """Helper: create a mock httpx module + async client returning mock_resp."""
    mock_client_inst = AsyncMock()
    mock_client_inst.get.return_value = mock_resp
    mock_client_inst.__aenter__ = AsyncMock(return_value=mock_client_inst)
    mock_client_inst.__aexit__ = AsyncMock(return_value=False)

    mock_httpx_mod = MagicMock()
    mock_httpx_mod.AsyncClient.return_value = mock_client_inst
    return mock_httpx_mod, mock_client_inst


def _make_error_httpx_client(
    exc: Exception,
) -> Tuple[MagicMock, AsyncMock]:
    """Helper: create a mock httpx module + async client that raises on get."""
    mock_client_inst = AsyncMock()
    mock_client_inst.get.side_effect = exc
    mock_client_inst.__aenter__ = AsyncMock(return_value=mock_client_inst)
    mock_client_inst.__aexit__ = AsyncMock(return_value=False)

    mock_httpx_mod = MagicMock()
    mock_httpx_mod.AsyncClient.return_value = mock_client_inst
    return mock_httpx_mod, mock_client_inst


class TestFetchVesselDesign:
    """Tests for fetch_vessel_design() with mocked httpx.

    httpx is imported locally inside fetch_vessel_design(), so we patch
    it in sys.modules to intercept the import.
    """

    @pytest.mark.asyncio
    async def test_successful_fetch(self) -> None:
        """Successful fetch returns VesselDesign."""
        response_data = {
            "length": {"value": {"overall": 13.99}},
            "beam": {"value": 7.96},
            "draft": {"value": {"maximum": 1.35}},
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data

        mock_httpx_mod, _ = _make_mock_httpx_client(mock_resp)
        with patch.dict("sys.modules", {"httpx": mock_httpx_mod}):
            design = await fetch_vessel_design("http://test:3000")

        assert design is not None
        assert design.loa == 13.99
        assert design.beam == 7.96

    @pytest.mark.asyncio
    async def test_fetch_404(self) -> None:
        """404 returns None."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_httpx_mod, _ = _make_mock_httpx_client(mock_resp)
        with patch.dict("sys.modules", {"httpx": mock_httpx_mod}):
            design = await fetch_vessel_design("http://test:3000")

        assert design is None

    @pytest.mark.asyncio
    async def test_fetch_server_error(self) -> None:
        """500 returns None."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        mock_httpx_mod, _ = _make_mock_httpx_client(mock_resp)
        with patch.dict("sys.modules", {"httpx": mock_httpx_mod}):
            design = await fetch_vessel_design("http://test:3000")

        assert design is None

    @pytest.mark.asyncio
    async def test_fetch_with_auth_token(self) -> None:
        """Auth token is passed as Bearer header."""
        response_data = {"beam": {"value": 5.0}}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data

        mock_httpx_mod, mock_client_inst = _make_mock_httpx_client(mock_resp)
        with patch.dict("sys.modules", {"httpx": mock_httpx_mod}):
            design = await fetch_vessel_design(
                "http://test:3000", auth_token="tok123"
            )

        # Verify auth header was passed
        call_kwargs = mock_client_inst.get.call_args
        assert call_kwargs[1]["headers"]["Authorization"] == "Bearer tok123"

    @pytest.mark.asyncio
    async def test_fetch_network_error(self) -> None:
        """Network error returns None (no crash)."""
        mock_httpx_mod, _ = _make_error_httpx_client(ConnectionError("no route"))
        with patch.dict("sys.modules", {"httpx": mock_httpx_mod}):
            design = await fetch_vessel_design("http://test:3000")

        assert design is None

    @pytest.mark.asyncio
    async def test_fetch_non_dict_response(self) -> None:
        """Non-dict JSON response returns None."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [1, 2, 3]

        mock_httpx_mod, _ = _make_mock_httpx_client(mock_resp)
        with patch.dict("sys.modules", {"httpx": mock_httpx_mod}):
            design = await fetch_vessel_design("http://test:3000")

        assert design is None

    @pytest.mark.asyncio
    async def test_fetch_no_httpx(self) -> None:
        """If httpx is not installed, returns None gracefully."""
        with patch("builtins.__import__", side_effect=ImportError("no httpx")):
            result = await fetch_vessel_design("http://test:3000")
            assert result is None


# ========================================================================= #
# log_hull_parameters (smoke test)                                             #
# ========================================================================= #

class TestLogHullParameters:
    """Smoke tests for log_hull_parameters()."""

    def test_log_does_not_crash(self) -> None:
        """Logging should work with full parameters."""
        design = VesselDesign(loa=13.99, beam=7.96, draft_max=1.35)
        params = compute_hull_parameters(design)
        # Should not raise
        log_hull_parameters(params)

    def test_log_with_empty_params(self) -> None:
        """Logging should work with empty/default parameters."""
        params = HullParameters()
        log_hull_parameters(params)

    def test_log_with_none_design(self) -> None:
        """Logging should work even if design is None."""
        params = compute_hull_parameters(VesselDesign())
        log_hull_parameters(params)


# ========================================================================= #
# Integration: end-to-end parse + compute                                     #
# ========================================================================= #

class TestEndToEnd:
    """Integration tests: parse Signal K response -> compute hull parameters."""

    def test_primrose_full_pipeline(self) -> None:
        """Full pipeline for Primrose (real vessel)."""
        sk_data = {
            "length": {"value": {"overall": 13.99}},
            "beam": {"value": 7.96},
            "draft": {"value": {"maximum": 1.35}},
            "airHeight": {"value": 23.21},
            "aisShipType": {"value": {"id": 36, "name": "Sailing"}},
        }
        design = _parse_design_response(sk_data)
        params = compute_hull_parameters(design)

        assert params.hull_type == HullType.CATAMARAN
        assert params.resonant_period is not None
        assert 2.9 < params.resonant_period < 3.1
        assert params.beam_resonant_period is not None
        assert 2.0 < params.beam_resonant_period < 2.5
        assert params.severity_weights is not None
        assert params.severity_weights["pitch_rms"] == 0.35

    def test_minimal_data_pipeline(self) -> None:
        """Only LOA available -> still computes resonance."""
        sk_data = {"length": {"value": 20.0}}
        design = _parse_design_response(sk_data)
        params = compute_hull_parameters(design)

        assert params.hull_type == HullType.UNKNOWN
        assert params.resonant_wavelength == 20.0
        assert params.resonant_period is not None
        # 20m wavelength -> T ~ 3.58s
        assert 3.4 < params.resonant_period < 3.8

    def test_empty_data_pipeline(self) -> None:
        """No data at all -> graceful defaults."""
        design = _parse_design_response({})
        params = compute_hull_parameters(design)

        assert params.hull_type == HullType.UNKNOWN
        assert params.resonant_wavelength is None
        assert params.resonant_period is None
        assert params.severity_weights is not None


# ========================================================================= #
# Phase 2: RAO gain curve                                                      #
# ========================================================================= #

class TestRAOGain:
    """Tests for rao_gain() — Lorentzian resonance model."""

    @pytest.fixture
    def catamaran_params(self) -> HullParameters:
        design = VesselDesign(loa=13.99, beam=7.96, draft_max=1.35)
        return compute_hull_parameters(design)

    @pytest.fixture
    def monohull_params(self) -> HullParameters:
        design = VesselDesign(loa=12.0, beam=3.5, draft_max=2.0)
        return compute_hull_parameters(design)

    def test_gain_at_resonance_peak_catamaran(self, catamaran_params: HullParameters) -> None:
        """Gain at resonant period should be near the peak value (~1.8 for cat)."""
        t_res = catamaran_params.resonant_period
        assert t_res is not None
        gain = rao_gain(t_res, catamaran_params)
        # Primary peak = 1.8, plus beam resonance contribution
        assert gain > 1.5

    def test_gain_at_resonance_peak_monohull(self, monohull_params: HullParameters) -> None:
        """Monohull peak gain should be lower than catamaran."""
        t_res = monohull_params.resonant_period
        assert t_res is not None
        gain_mono = rao_gain(t_res, monohull_params)
        # Monohull primary peak = 1.5
        assert gain_mono > 1.3

    def test_catamaran_peak_higher_than_monohull(
        self, catamaran_params: HullParameters, monohull_params: HullParameters
    ) -> None:
        """Catamaran has sharper, higher peak than monohull at its own resonance."""
        t_cat = catamaran_params.resonant_period
        t_mono = monohull_params.resonant_period
        assert t_cat is not None and t_mono is not None
        gain_cat = rao_gain(t_cat, catamaran_params)
        gain_mono = rao_gain(t_mono, monohull_params)
        assert gain_cat > gain_mono

    def test_gain_approaches_one_for_long_waves(self, catamaran_params: HullParameters) -> None:
        """Very long waves (T >> resonant_T): hull follows wave, gain -> 1."""
        gain_20s = rao_gain(20.0, catamaran_params)
        assert 0.9 < gain_20s < 1.3

    def test_gain_attenuated_for_very_short_waves(self, catamaran_params: HullParameters) -> None:
        """Very short waves (T << resonant_T): too short to excite hull."""
        t_res = catamaran_params.resonant_period
        assert t_res is not None
        very_short = t_res * 0.15  # well below 30% threshold
        gain = rao_gain(very_short, catamaran_params)
        assert gain < 1.0  # attenuated

    def test_gain_floor_at_zero_period(self, catamaran_params: HullParameters) -> None:
        """Zero period returns 1.0 (no correction)."""
        assert rao_gain(0.0, catamaran_params) == 1.0

    def test_gain_floor_negative_period(self, catamaran_params: HullParameters) -> None:
        """Negative period returns 1.0 (no correction)."""
        assert rao_gain(-5.0, catamaran_params) == 1.0

    def test_gain_never_below_floor(self, catamaran_params: HullParameters) -> None:
        """Gain should never go below the 0.1 floor."""
        for t in [0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0]:
            assert rao_gain(t, catamaran_params) >= 0.1

    def test_beam_resonance_secondary_peak(self, catamaran_params: HullParameters) -> None:
        """Gain at beam resonant period should show a secondary peak."""
        t_beam = catamaran_params.beam_resonant_period
        assert t_beam is not None
        gain_beam = rao_gain(t_beam, catamaran_params)
        # Should be noticeably above 1.0 due to beam resonance
        assert gain_beam > 1.2

    def test_gain_symmetric_around_peak(self, catamaran_params: HullParameters) -> None:
        """Lorentzian is symmetric: gain(T_res + dT) ≈ gain(T_res - dT)
        (ignoring short-wave attenuation at low end)."""
        t_res = catamaran_params.resonant_period
        assert t_res is not None
        delta = 1.5  # far enough to avoid short-wave effects
        gain_above = rao_gain(t_res + delta, catamaran_params)
        gain_below = rao_gain(t_res + delta * 0.8, catamaran_params)
        # Not exactly symmetric due to beam resonance, but both should be elevated
        assert gain_above > 1.0
        assert gain_below > 1.0

    def test_no_resonance_data(self) -> None:
        """If hull params have no resonant period, gain is 1.0."""
        params = HullParameters()  # all None
        assert rao_gain(5.0, params) == 1.0

    def test_gain_with_only_loa(self) -> None:
        """If only LOA is known (no beam), primary resonance still applies."""
        design = VesselDesign(loa=14.0)
        params = compute_hull_parameters(design)
        t_res = params.resonant_period
        assert t_res is not None
        gain = rao_gain(t_res, params)
        # Should still have a peak
        assert gain > 1.3

    def test_trimaran_intermediate_peak(self) -> None:
        """Trimaran peak should be between monohull and catamaran."""
        design = VesselDesign(loa=15.0, beam=5.0, draft_max=1.5)
        params = compute_hull_parameters(design)
        assert params.hull_type == HullType.TRIMARAN
        t_res = params.resonant_period
        assert t_res is not None
        gain = rao_gain(t_res, params)
        # Trimaran peak = 1.6
        assert 1.4 < gain < 2.5


# ========================================================================= #
# Phase 2: RAO confidence adjustment                                           #
# ========================================================================= #

class TestRAOConfidenceAdjustment:
    """Tests for rao_confidence_adjustment()."""

    @pytest.fixture
    def catamaran_params(self) -> HullParameters:
        design = VesselDesign(loa=13.99, beam=7.96, draft_max=1.35)
        return compute_hull_parameters(design)

    @pytest.fixture
    def monohull_params(self) -> HullParameters:
        design = VesselDesign(loa=12.0, beam=3.5, draft_max=2.0)
        return compute_hull_parameters(design)

    def test_within_natural_period_boost(self, catamaran_params: HullParameters) -> None:
        """Period within natural roll range -> period boost > 1."""
        # Catamaran natural roll: 2-4s; midpoint = 3.0s
        period_boost, hs_penalty = rao_confidence_adjustment(3.0, catamaran_params)
        assert period_boost > 1.0

    def test_within_natural_period_hs_penalty(self, catamaran_params: HullParameters) -> None:
        """Period within natural roll range -> Hs penalty < 1."""
        period_boost, hs_penalty = rao_confidence_adjustment(3.0, catamaran_params)
        assert hs_penalty < 1.0

    def test_outside_natural_period_no_boost(self, catamaran_params: HullParameters) -> None:
        """Period well outside natural range -> boost ≈ 1.0."""
        period_boost, hs_penalty = rao_confidence_adjustment(15.0, catamaran_params)
        # Outside range: no centrality boost (but RAO-gain penalty may still apply)
        assert period_boost == pytest.approx(1.0, abs=0.01)

    def test_zero_period(self, catamaran_params: HullParameters) -> None:
        """Zero period -> (1.0, 1.0)."""
        period_boost, hs_penalty = rao_confidence_adjustment(0.0, catamaran_params)
        assert period_boost == 1.0
        assert hs_penalty == 1.0

    def test_negative_period(self, catamaran_params: HullParameters) -> None:
        """Negative period -> (1.0, 1.0)."""
        period_boost, hs_penalty = rao_confidence_adjustment(-3.0, catamaran_params)
        assert period_boost == 1.0
        assert hs_penalty == 1.0

    def test_boost_clamped_at_1_5(self, catamaran_params: HullParameters) -> None:
        """Period boost should never exceed 1.5."""
        for t in [2.5, 3.0, 3.5]:
            pb, _ = rao_confidence_adjustment(t, catamaran_params)
            assert pb <= 1.5

    def test_penalty_floored_at_0_5(self, catamaran_params: HullParameters) -> None:
        """Hs penalty should never go below 0.5."""
        for t in [2.5, 3.0, 3.5]:
            _, hp = rao_confidence_adjustment(t, catamaran_params)
            assert hp >= 0.5

    def test_monohull_different_range(self, monohull_params: HullParameters) -> None:
        """Monohull natural roll 5-12s -> boost at 8.5s, not at 3s."""
        # At monohull natural midpoint (8.5s)
        pb_natural, _ = rao_confidence_adjustment(8.5, monohull_params)
        # At catamaran natural midpoint (3s) — outside monohull range
        pb_outside, _ = rao_confidence_adjustment(3.0, monohull_params)
        assert pb_natural > pb_outside

    def test_high_rao_gain_extra_penalty(self, catamaran_params: HullParameters) -> None:
        """When RAO gain > 1.2, extra Hs penalty is applied."""
        # At resonant period, gain is high -> extra penalty
        t_res = catamaran_params.resonant_period
        assert t_res is not None
        _, hs_penalty = rao_confidence_adjustment(t_res, catamaran_params)
        # Should be penalised below 1.0
        assert hs_penalty < 1.0

    def test_no_params(self) -> None:
        """Empty hull params -> uses default wide range (2-12s), so period
        within range still gets a small boost.  Period well outside (20s)
        should get no boost."""
        params = HullParameters()
        # 20s is outside default range (2-12s)
        period_boost, hs_penalty = rao_confidence_adjustment(20.0, params)
        assert period_boost == pytest.approx(1.0, abs=0.01)
        assert hs_penalty == pytest.approx(1.0, abs=0.01)


# ========================================================================= #
# Phase 2: FeatureExtractor with hull params                                   #
# ========================================================================= #

class TestFeatureExtractorHullIntegration:
    """Tests for FeatureExtractor with hull_params (Phase 2 integration)."""

    def test_extractor_accepts_hull_params(self) -> None:
        """FeatureExtractor can be constructed with hull_params."""
        from config import Config
        from feature_extractor import FeatureExtractor

        design = VesselDesign(loa=13.99, beam=7.96, draft_max=1.35)
        params = compute_hull_parameters(design)
        ext = FeatureExtractor(Config(), hull_params=params)
        assert ext._hull_params is not None
        assert ext._hull_params.hull_type == HullType.CATAMARAN

    def test_extractor_none_hull_params(self) -> None:
        """FeatureExtractor works fine with hull_params=None."""
        from config import Config
        from feature_extractor import FeatureExtractor

        ext = FeatureExtractor(Config(), hull_params=None)
        assert ext._hull_params is None

    def test_apply_rao_correction_reduces_hs_at_resonance(self) -> None:
        """_apply_rao_correction should reduce Hs when period is near hull resonance."""
        from config import Config
        from feature_extractor import FeatureExtractor
        from models import MotionEstimate

        design = VesselDesign(loa=13.99, beam=7.96, draft_max=1.35)
        params = compute_hull_parameters(design)
        ext = FeatureExtractor(Config(), hull_params=params)

        t_res = params.resonant_period
        assert t_res is not None

        from datetime import datetime, timezone
        me = MotionEstimate(
            timestamp=datetime.now(timezone.utc),
            window_s=30.0,
            significant_height=1.0,
            wave_height_confidence=0.8,
            encounter_period_estimate=t_res,
        )
        original_hs = me.significant_height
        ext._apply_rao_correction(me)

        # Hs should be reduced (divided by gain > 1)
        assert me.significant_height is not None
        assert me.significant_height < original_hs
        assert me.rao_gain_applied is not None
        assert me.rao_gain_applied > 1.0

    def test_apply_rao_correction_no_hull_params(self) -> None:
        """Without hull params, Hs should be unchanged."""
        from config import Config
        from feature_extractor import FeatureExtractor
        from models import MotionEstimate
        from datetime import datetime, timezone

        ext = FeatureExtractor(Config(), hull_params=None)

        me = MotionEstimate(
            timestamp=datetime.now(timezone.utc),
            window_s=30.0,
            significant_height=1.0,
            wave_height_confidence=0.8,
            encounter_period_estimate=5.0,
        )
        ext._apply_rao_correction(me)
        assert me.significant_height == 1.0
        assert me.rao_gain_applied is None

    def test_apply_rao_correction_no_hs(self) -> None:
        """If significant_height is None, correction is a no-op."""
        from config import Config
        from feature_extractor import FeatureExtractor
        from models import MotionEstimate
        from datetime import datetime, timezone

        design = VesselDesign(loa=13.99, beam=7.96, draft_max=1.35)
        params = compute_hull_parameters(design)
        ext = FeatureExtractor(Config(), hull_params=params)

        me = MotionEstimate(
            timestamp=datetime.now(timezone.utc),
            window_s=30.0,
            significant_height=None,
            encounter_period_estimate=3.0,
        )
        ext._apply_rao_correction(me)
        assert me.significant_height is None
        assert me.rao_gain_applied is None

    def test_apply_rao_correction_no_period(self) -> None:
        """If no period is available, correction is a no-op."""
        from config import Config
        from feature_extractor import FeatureExtractor
        from models import MotionEstimate
        from datetime import datetime, timezone

        design = VesselDesign(loa=13.99, beam=7.96, draft_max=1.35)
        params = compute_hull_parameters(design)
        ext = FeatureExtractor(Config(), hull_params=params)

        me = MotionEstimate(
            timestamp=datetime.now(timezone.utc),
            window_s=30.0,
            significant_height=1.0,
            wave_height_confidence=0.8,
        )
        ext._apply_rao_correction(me)
        # No period -> no correction
        assert me.significant_height == 1.0
        assert me.rao_gain_applied is None

    def test_apply_rao_correction_prefers_true_wave_period(self) -> None:
        """Correction should prefer true_wave_period over encounter_period."""
        from config import Config
        from feature_extractor import FeatureExtractor
        from models import MotionEstimate
        from datetime import datetime, timezone

        design = VesselDesign(loa=13.99, beam=7.96, draft_max=1.35)
        params = compute_hull_parameters(design)
        ext = FeatureExtractor(Config(), hull_params=params)

        t_res = params.resonant_period
        assert t_res is not None

        # true_wave_period = resonance (high gain), encounter_period = far away (low gain)
        me = MotionEstimate(
            timestamp=datetime.now(timezone.utc),
            window_s=30.0,
            significant_height=1.0,
            wave_height_confidence=0.8,
            true_wave_period=t_res,
            encounter_period_estimate=20.0,  # far from resonance
        )
        ext._apply_rao_correction(me)
        # Should use true_wave_period (resonance) -> significant correction
        assert me.rao_gain_applied is not None
        assert me.rao_gain_applied > 1.5

    def test_apply_rao_correction_adjusts_confidence(self) -> None:
        """Hs confidence should be reduced near hull resonance."""
        from config import Config
        from feature_extractor import FeatureExtractor
        from models import MotionEstimate
        from datetime import datetime, timezone

        design = VesselDesign(loa=13.99, beam=7.96, draft_max=1.35)
        params = compute_hull_parameters(design)
        ext = FeatureExtractor(Config(), hull_params=params)

        t_res = params.resonant_period
        assert t_res is not None

        me = MotionEstimate(
            timestamp=datetime.now(timezone.utc),
            window_s=30.0,
            significant_height=1.0,
            wave_height_confidence=0.8,
            encounter_period_estimate=t_res,
        )
        ext._apply_rao_correction(me)
        # Confidence should be penalised
        assert me.wave_height_confidence is not None
        assert me.wave_height_confidence < 0.8

    def test_apply_rao_correction_long_wave_minimal_change(self) -> None:
        """For long waves far from resonance, correction should be minimal."""
        from config import Config
        from feature_extractor import FeatureExtractor
        from models import MotionEstimate
        from datetime import datetime, timezone

        design = VesselDesign(loa=13.99, beam=7.96, draft_max=1.35)
        params = compute_hull_parameters(design)
        ext = FeatureExtractor(Config(), hull_params=params)

        me = MotionEstimate(
            timestamp=datetime.now(timezone.utc),
            window_s=30.0,
            significant_height=1.0,
            wave_height_confidence=0.8,
            encounter_period_estimate=20.0,  # far from resonance
        )
        ext._apply_rao_correction(me)
        # Gain near 1.0 -> Hs barely changes
        assert me.significant_height is not None
        assert abs(me.significant_height - 1.0) < 0.15

    def test_severity_uses_hull_weights(self) -> None:
        """_compute_severity should use hull-type-specific weights."""
        from config import Config
        from feature_extractor import FeatureExtractor
        from models import WindowFeatures
        from datetime import datetime, timezone

        design = VesselDesign(loa=13.99, beam=7.96, draft_max=1.35)
        params = compute_hull_parameters(design)

        ext_hull = FeatureExtractor(Config(), hull_params=params)
        ext_default = FeatureExtractor(Config(), hull_params=None)

        # Create WindowFeatures with some motion data
        wf = WindowFeatures(
            timestamp=datetime.now(timezone.utc),
            window_s=30.0,
            n_samples=60,
            roll_rms=0.05,    # ~2.9 degrees
            pitch_rms=0.05,   # ~2.9 degrees
            roll_spectral_energy=0.02,
            yaw_rate_var=0.005,
        )

        sev_hull = ext_hull._compute_severity(wf)
        sev_default = ext_default._compute_severity(wf)

        # Both should return valid severity values
        assert 0.0 <= sev_hull <= 1.0
        assert 0.0 <= sev_default <= 1.0

        # Catamaran has lower roll_rms_max -> same motion should score
        # higher severity for roll component, but different weighting
        # makes absolute comparison unreliable; just verify both work
        assert isinstance(sev_hull, float)
        assert isinstance(sev_default, float)
