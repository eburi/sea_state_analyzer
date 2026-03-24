"""Tests for the engine facade (src/engine.py).

Covers:
  1. Engine selection logic (python / rust / fallback)
  2. Python-engine dispatch for trochoidal, Kalman, and combined estimation
  3. Type compatibility: engine facade returns canonical heave_estimator types
  4. Backwards-compatible aliases (EngineHeaveEstimate, EngineTrochoidalEstimate)
"""

from __future__ import annotations

import math
from dataclasses import fields
from unittest.mock import MagicMock, patch

import numpy as np

from config import Config, DEFAULT_CONFIG
from engine import (
    EngineHeaveEstimate,
    EngineTrochoidalEstimate,
    RustKalmanHeaveEstimator,
    estimate_waves_from_accel,
    get_rust_module,
    make_kalman_heave_estimator,
    rust_engine_available,
    selected_engine,
    trochoidal_wave_height,
)
from heave_estimator import (
    HeaveEstimate,
    KalmanHeaveEstimator,
    TrochoidalEstimate,
    WaveEstimate,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _python_config() -> Config:
    """Config that forces the Python engine."""
    return Config(engine="python")


def _rust_config() -> Config:
    """Config that requests the Rust engine (may not be available)."""
    return Config(engine="rust")


def _sine_accel(
    freq_hz: float = 0.1,
    amplitude: float = 0.5,
    duration_s: float = 30.0,
    fs: float = 50.0,
) -> np.ndarray:
    """Generate a simple sinusoidal vertical-acceleration signal."""
    t = np.arange(0, duration_s, 1.0 / fs)
    return amplitude * np.sin(2.0 * math.pi * freq_hz * t)


# --------------------------------------------------------------------------- #
# 1. Engine selection                                                          #
# --------------------------------------------------------------------------- #


class TestEngineSelection:
    def test_python_engine_selected_by_default(self) -> None:
        assert selected_engine(DEFAULT_CONFIG) == "python"

    def test_python_engine_when_explicitly_set(self) -> None:
        assert selected_engine(_python_config()) == "python"

    def test_rust_requested_but_unavailable_falls_back(self) -> None:
        """When engine='rust' but the extension isn't installed, fall back."""
        with patch("engine._load_rust_module", return_value=None):
            assert selected_engine(_rust_config()) == "python"

    def test_rust_requested_and_available(self) -> None:
        mock_mod = MagicMock()
        with patch("engine._load_rust_module", return_value=mock_mod):
            assert selected_engine(_rust_config()) == "rust"

    def test_get_rust_module_returns_none_for_python_engine(self) -> None:
        assert get_rust_module(_python_config()) is None

    def test_get_rust_module_returns_none_when_unavailable(self) -> None:
        with patch("engine._load_rust_module", return_value=None):
            assert get_rust_module(_rust_config()) is None

    def test_rust_engine_available_false(self) -> None:
        with patch("engine._load_rust_module", return_value=None):
            assert rust_engine_available() is False

    def test_rust_engine_available_true(self) -> None:
        mock_mod = MagicMock()
        with patch("engine._load_rust_module", return_value=mock_mod):
            assert rust_engine_available() is True


# --------------------------------------------------------------------------- #
# 2. Type compatibility                                                        #
# --------------------------------------------------------------------------- #


class TestTypeCompatibility:
    def test_engine_aliases_are_canonical_types(self) -> None:
        """EngineTrochoidalEstimate and EngineHeaveEstimate must be the
        canonical types from heave_estimator, not separate dataclasses."""
        assert EngineTrochoidalEstimate is TrochoidalEstimate
        assert EngineHeaveEstimate is HeaveEstimate

    def test_heave_estimate_field_order_matches_rust_tuple(self) -> None:
        """Verify field order matches what the Rust PyO3 get_estimate returns:
        (heave_displacement, heave_amplitude, significant_height, heave_std,
         heave_max, heave_min, n_samples, converged, method)."""
        expected_names = [
            "heave_displacement",
            "heave_amplitude",
            "significant_height",
            "heave_std",
            "heave_max",
            "heave_min",
            "n_samples",
            "converged",
            "method",
        ]
        actual_names = [f.name for f in fields(HeaveEstimate)]
        assert actual_names == expected_names

    def test_trochoidal_estimate_field_order_matches_rust_tuple(self) -> None:
        """Verify field order matches what the Rust PyO3 trochoidal returns:
        (significant_height, wave_amplitude, wavelength, wave_speed,
         b_parameter, accel_max, frequency_hz, method)."""
        expected_names = [
            "significant_height",
            "wave_amplitude",
            "wavelength",
            "wave_speed",
            "b_parameter",
            "accel_max",
            "frequency_hz",
            "method",
        ]
        actual_names = [f.name for f in fields(TrochoidalEstimate)]
        assert actual_names == expected_names

    def test_heave_estimate_constructable_from_tuple(self) -> None:
        """HeaveEstimate must be constructable from a positional tuple
        (the way RustKalmanHeaveEstimator.get_estimate unpacks the result)."""
        values = (0.1, 0.2, 0.8, 0.2, 0.4, -0.3, 500, True, "kalman")
        est = HeaveEstimate(*values)
        assert est.heave_displacement == 0.1
        assert est.converged is True
        assert est.method == "kalman"

    def test_trochoidal_estimate_constructable_from_tuple(self) -> None:
        values = (1.0, 0.5, 100.0, 12.5, -0.3, 0.5, 0.1, "trochoidal")
        est = TrochoidalEstimate(*values)
        assert est.significant_height == 1.0
        assert est.method == "trochoidal"


# --------------------------------------------------------------------------- #
# 3. Python-engine trochoidal dispatch                                         #
# --------------------------------------------------------------------------- #


class TestTrochoidalDispatch:
    def test_basic_trochoidal_returns_canonical_type(self) -> None:
        result = trochoidal_wave_height(
            accel_max_observed=0.5,
            frequency_hz=0.1,
            config=_python_config(),
        )
        assert result is not None
        assert isinstance(result, TrochoidalEstimate)
        assert result.significant_height > 0
        assert result.wavelength > 0
        assert result.method == "trochoidal"

    def test_trochoidal_returns_none_for_invalid_inputs(self) -> None:
        # Frequency out of range
        assert trochoidal_wave_height(0.5, 0.001, config=_python_config()) is None
        # Accel too small
        assert trochoidal_wave_height(0.001, 0.1, config=_python_config()) is None

    def test_trochoidal_with_doppler(self) -> None:
        result = trochoidal_wave_height(
            accel_max_observed=0.5,
            frequency_hz=0.1,
            delta_v=1.5,
            config=_python_config(),
        )
        assert result is not None
        assert result.significant_height > 0

    def test_trochoidal_none_config_uses_default(self) -> None:
        """Calling without explicit config should use DEFAULT_CONFIG (python)."""
        result = trochoidal_wave_height(0.5, 0.1)
        assert result is not None
        assert isinstance(result, TrochoidalEstimate)


# --------------------------------------------------------------------------- #
# 4. Python-engine Kalman factory                                              #
# --------------------------------------------------------------------------- #


class TestKalmanFactory:
    def test_make_kalman_returns_python_estimator(self) -> None:
        est = make_kalman_heave_estimator(_python_config())
        assert isinstance(est, KalmanHeaveEstimator)

    def test_kalman_estimator_update_and_estimate(self) -> None:
        est = make_kalman_heave_estimator(_python_config())
        accel = _sine_accel(freq_hz=0.2, duration_s=10.0)
        for sample in accel:
            est.update(float(sample))
        result = est.get_estimate(min_samples=100)
        assert result is not None
        assert isinstance(result, HeaveEstimate)
        assert result.n_samples > 0

    def test_kalman_estimator_properties(self) -> None:
        est = make_kalman_heave_estimator(_python_config())
        est.update(0.1)
        assert isinstance(est.displacement, float)
        assert isinstance(est.velocity, float)
        assert isinstance(est.n_processed, int)
        assert est.n_processed == 1

    def test_kalman_estimator_reset(self) -> None:
        est = make_kalman_heave_estimator(_python_config())
        for _ in range(200):
            est.update(0.1)
        est.reset()
        assert est.n_processed == 0

    def test_make_kalman_with_rust_unavailable_falls_back(self) -> None:
        """When rust requested but not available, should return Python impl."""
        with patch("engine._load_rust_module", return_value=None):
            est = make_kalman_heave_estimator(_rust_config())
            assert isinstance(est, KalmanHeaveEstimator)


# --------------------------------------------------------------------------- #
# 5. Python-engine combined estimation dispatch                                #
# --------------------------------------------------------------------------- #


class TestEstimateWavesDispatch:
    def test_basic_wave_estimate(self) -> None:
        accel = _sine_accel(freq_hz=0.1, amplitude=0.5, duration_s=30.0)
        result = estimate_waves_from_accel(
            vertical_accel=accel,
            fs=50.0,
            config=_python_config(),
        )
        assert isinstance(result, WaveEstimate)
        assert result.accel_rms is not None
        assert result.accel_rms > 0

    def test_wave_estimate_has_dominant_freq(self) -> None:
        accel = _sine_accel(freq_hz=0.1, amplitude=0.5, duration_s=60.0)
        result = estimate_waves_from_accel(
            vertical_accel=accel,
            fs=50.0,
            config=_python_config(),
        )
        assert result.accel_dominant_freq is not None
        # Should be close to 0.1 Hz
        assert abs(result.accel_dominant_freq - 0.1) < 0.05

    def test_wave_estimate_too_few_samples(self) -> None:
        accel = np.array([0.1, 0.2, 0.3])
        result = estimate_waves_from_accel(
            vertical_accel=accel,
            fs=50.0,
            config=_python_config(),
        )
        assert isinstance(result, WaveEstimate)
        assert result.significant_height is None

    def test_config_parameter_not_forwarded(self) -> None:
        """The config kwarg should be consumed by the engine facade,
        not forwarded to the Python implementation (which doesn't accept it)."""
        accel = _sine_accel()
        # This should NOT raise TypeError about unexpected 'config' kwarg
        result = estimate_waves_from_accel(
            vertical_accel=accel,
            fs=50.0,
            config=_python_config(),
        )
        assert isinstance(result, WaveEstimate)

    def test_explicit_kwargs_forwarded(self) -> None:
        accel = _sine_accel()
        result = estimate_waves_from_accel(
            vertical_accel=accel,
            fs=50.0,
            freq_min_hz=0.05,
            freq_max_hz=0.5,
            lowpass_cutoff_mult=4.0,
            trochoidal_min_amplitude=0.01,
            config=_python_config(),
        )
        assert isinstance(result, WaveEstimate)


# --------------------------------------------------------------------------- #
# 6. RustKalmanHeaveEstimator with mock module                                 #
# --------------------------------------------------------------------------- #


class TestRustKalmanHeaveEstimatorMock:
    """Test the wrapper class with a mocked Rust module."""

    def _make_mock_module(self) -> MagicMock:
        """Create a mock that behaves like the PyO3 module."""
        mock_mod = MagicMock()
        mock_inner = MagicMock()
        mock_inner.update.return_value = 0.05
        mock_inner.displacement = 0.05
        mock_inner.velocity = 0.01
        mock_inner.n_processed = 10
        # get_estimate returns a tuple matching HeaveEstimate field order
        mock_inner.get_estimate.return_value = (
            0.05,
            0.1,
            0.4,
            0.1,
            0.2,
            -0.15,
            200,
            True,
            "kalman",
        )
        mock_mod.PyKalmanHeaveEstimator.return_value = mock_inner
        return mock_mod

    def test_wrapper_update(self) -> None:
        mock_mod = self._make_mock_module()
        est = RustKalmanHeaveEstimator(
            dt=0.02,
            pos_integral_trans_var=1e-6,
            pos_trans_var=1e-4,
            vel_trans_var=1e-2,
            pos_integral_obs_var=1e-1,
            accel_bias_window=500,
            module=mock_mod,
        )
        result = est.update(0.3)
        assert isinstance(result, float)
        assert result == 0.05

    def test_wrapper_get_estimate_returns_heave_estimate(self) -> None:
        mock_mod = self._make_mock_module()
        est = RustKalmanHeaveEstimator(
            dt=0.02,
            pos_integral_trans_var=1e-6,
            pos_trans_var=1e-4,
            vel_trans_var=1e-2,
            pos_integral_obs_var=1e-1,
            accel_bias_window=500,
            module=mock_mod,
        )
        result = est.get_estimate()
        assert result is not None
        assert isinstance(result, HeaveEstimate)
        assert result.heave_displacement == 0.05
        assert result.converged is True

    def test_wrapper_get_estimate_returns_none(self) -> None:
        mock_mod = self._make_mock_module()
        mock_mod.PyKalmanHeaveEstimator.return_value.get_estimate.return_value = None
        est = RustKalmanHeaveEstimator(
            dt=0.02,
            pos_integral_trans_var=1e-6,
            pos_trans_var=1e-4,
            vel_trans_var=1e-2,
            pos_integral_obs_var=1e-1,
            accel_bias_window=500,
            module=mock_mod,
        )
        assert est.get_estimate() is None

    def test_wrapper_properties(self) -> None:
        mock_mod = self._make_mock_module()
        est = RustKalmanHeaveEstimator(
            dt=0.02,
            pos_integral_trans_var=1e-6,
            pos_trans_var=1e-4,
            vel_trans_var=1e-2,
            pos_integral_obs_var=1e-1,
            accel_bias_window=500,
            module=mock_mod,
        )
        assert est.displacement == 0.05
        assert est.velocity == 0.01
        assert est.n_processed == 10

    def test_wrapper_reset(self) -> None:
        mock_mod = self._make_mock_module()
        est = RustKalmanHeaveEstimator(
            dt=0.02,
            pos_integral_trans_var=1e-6,
            pos_trans_var=1e-4,
            vel_trans_var=1e-2,
            pos_integral_obs_var=1e-1,
            accel_bias_window=500,
            module=mock_mod,
        )
        est.reset(initial_displacement=1.0, initial_velocity=0.5)
        mock_mod.PyKalmanHeaveEstimator.return_value.reset.assert_called_once_with(
            initial_displacement=1.0, initial_velocity=0.5
        )
