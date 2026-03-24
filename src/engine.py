"""Runtime selection for optional Rust acceleration.

The Python implementation remains the source of truth.  When
`Config.engine == "rust"`, callers can import helpers from this module to
attempt loading the compiled PyO3 extension and fall back gracefully.
"""

from __future__ import annotations

import importlib
import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from config import Config, DEFAULT_CONFIG
from heave_estimator import HeaveEstimate, TrochoidalEstimate

if TYPE_CHECKING:
    from heave_estimator import WaveEstimate

# Backwards-compatible aliases for any external code that imported these.
EngineTrochoidalEstimate = TrochoidalEstimate
EngineHeaveEstimate = HeaveEstimate

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_rust_module() -> Any | None:
    try:
        return importlib.import_module("sea_state_engine")
    except ImportError:
        logger.debug("Rust engine module not available; using Python fallback")
        return None


def rust_engine_available() -> bool:
    return _load_rust_module() is not None


def selected_engine(config: Config = DEFAULT_CONFIG) -> str:
    if config.engine == "rust" and rust_engine_available():
        return "rust"
    return "python"


def get_rust_module(config: Config = DEFAULT_CONFIG) -> Any | None:
    if config.engine != "rust":
        return None
    return _load_rust_module()


class RustKalmanHeaveEstimator:
    def __init__(
        self,
        *,
        dt: float,
        pos_integral_trans_var: float,
        pos_trans_var: float,
        vel_trans_var: float,
        pos_integral_obs_var: float,
        accel_bias_window: int,
        module: Any,
    ) -> None:
        self._inner = module.PyKalmanHeaveEstimator(
            dt=dt,
            pos_integral_trans_var=pos_integral_trans_var,
            pos_trans_var=pos_trans_var,
            vel_trans_var=vel_trans_var,
            pos_integral_obs_var=pos_integral_obs_var,
            accel_bias_window=accel_bias_window,
        )

    def reset(
        self, initial_displacement: float = 0.0, initial_velocity: float = 0.0
    ) -> None:
        self._inner.reset(
            initial_displacement=initial_displacement, initial_velocity=initial_velocity
        )

    def update(self, vertical_accel: float) -> float:
        return float(self._inner.update(vertical_accel))

    def get_estimate(self, min_samples: int = 100) -> HeaveEstimate | None:
        result = self._inner.get_estimate(min_samples=min_samples)
        if result is None:
            return None
        return HeaveEstimate(*result)

    @property
    def displacement(self) -> float:
        return float(self._inner.displacement)

    @property
    def velocity(self) -> float:
        return float(self._inner.velocity)

    @property
    def n_processed(self) -> int:
        return int(self._inner.n_processed)


def make_kalman_heave_estimator(config: Config = DEFAULT_CONFIG) -> Any:
    module = get_rust_module(config)
    if module is not None:
        return RustKalmanHeaveEstimator(
            dt=1.0 / config.imu_sample_rate_hz,
            pos_integral_trans_var=config.heave_kalman_pos_integral_trans_var,
            pos_trans_var=config.heave_kalman_pos_trans_var,
            vel_trans_var=config.heave_kalman_vel_trans_var,
            pos_integral_obs_var=config.heave_kalman_pos_integral_obs_var,
            accel_bias_window=config.heave_kalman_bias_window,
            module=module,
        )
    from heave_estimator import KalmanHeaveEstimator as PythonKalmanHeaveEstimator

    return PythonKalmanHeaveEstimator(
        dt=1.0 / config.imu_sample_rate_hz,
        pos_integral_trans_var=config.heave_kalman_pos_integral_trans_var,
        pos_trans_var=config.heave_kalman_pos_trans_var,
        vel_trans_var=config.heave_kalman_vel_trans_var,
        pos_integral_obs_var=config.heave_kalman_pos_integral_obs_var,
        accel_bias_window=config.heave_kalman_bias_window,
    )


def trochoidal_wave_height(
    accel_max_observed: float,
    frequency_hz: float,
    delta_v: float = 0.0,
    min_amplitude: float = 0.005,
    config: Config = DEFAULT_CONFIG,
) -> TrochoidalEstimate | None:
    module = get_rust_module(config)
    if module is None:
        from heave_estimator import (
            trochoidal_wave_height as python_trochoidal_wave_height,
        )

        return python_trochoidal_wave_height(
            accel_max_observed=accel_max_observed,
            frequency_hz=frequency_hz,
            delta_v=delta_v,
            min_amplitude=min_amplitude,
        )
    result = module.trochoidal_wave_height(
        accel_max_observed, frequency_hz, delta_v, min_amplitude
    )
    if result is None:
        return None
    return TrochoidalEstimate(*result)


def estimate_waves_from_accel(
    vertical_accel: Any,
    fs: float,
    delta_v: float = 0.0,
    kalman_estimator: Any = None,
    lowpass_cutoff_mult: float = 8.0,
    psd_min_samples: int = 32,
    freq_min_hz: float = 0.03,
    freq_max_hz: float = 1.0,
    trochoidal_min_amplitude: float = 0.005,
    hull_params: Any = None,
    config: Config = DEFAULT_CONFIG,
) -> "WaveEstimate":
    from heave_estimator import (
        estimate_waves_from_accel as python_estimate_waves_from_accel,
    )

    # Keep the full Python implementation as the source of truth for now.
    # Rust is already used for the trochoidal primitive and optional Kalman state.
    # The ``config`` parameter controls engine selection but is not forwarded to
    # the Python implementation (which has no concept of engine selection).
    return python_estimate_waves_from_accel(
        vertical_accel=vertical_accel,
        fs=fs,
        delta_v=delta_v,
        kalman_estimator=kalman_estimator,
        lowpass_cutoff_mult=lowpass_cutoff_mult,
        psd_min_samples=psd_min_samples,
        freq_min_hz=freq_min_hz,
        freq_max_hz=freq_max_hz,
        trochoidal_min_amplitude=trochoidal_min_amplitude,
        hull_params=hull_params,
    )
