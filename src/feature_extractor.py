"""Feature extraction pipeline.

Three layers:
  A  – instantaneous derived values (derivatives, heading-COG, etc.)
  B  – rolling-window motion statistics (RMS, PSD, spectral entropy, …)
  C  – inferred wave-motion proxies (severity, direction, regularity, trend)

All signal-processing code is isolated here so it can be swapped for
optimised implementations without touching the rest of the pipeline.

IMPORTANT DOMAIN NOTE:
  All outputs are inferences about vessel motion response to sea state.
  They are NOT direct measurements of wave height, direction, or period.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np
from scipy import signal as scipy_signal
from scipy.stats import kurtosis as scipy_kurtosis

from config import Config, DEFAULT_CONFIG
from models import InstantSample, LayerAFeatures, MotionEstimate, WindowFeatures

# Heave/wave height estimation (optional -- degrades gracefully if unavailable)
try:
    from heave_estimator import (
        KalmanHeaveEstimator,
        WaveEstimate,  # noqa: F401
        estimate_waves_from_accel,
    )

    _HEAVE_AVAILABLE = True
except ImportError:
    _HEAVE_AVAILABLE = False

# Vessel hull parameters (optional -- degrades gracefully)
try:
    from vessel_config import HullParameters, rao_gain, rao_confidence_adjustment  # noqa: F401

    _HULL_AVAILABLE = True
except ImportError:
    _HULL_AVAILABLE = False

# Online sea-state learner (optional -- degrades gracefully)
try:
    from sea_state_learner import SeaStateLearner  # noqa: F401

    _LEARNER_AVAILABLE = True
except ImportError:
    _LEARNER_AVAILABLE = False

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Low-level signal-processing utilities                                        #
# --------------------------------------------------------------------------- #


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x**2)))


def _crest_factor(x: np.ndarray) -> Optional[float]:
    r = _rms(x)
    if r == 0:
        return None
    return float(np.max(np.abs(x)) / r)


def _zero_crossing_period(x: np.ndarray, fs: float) -> Optional[float]:
    """Estimate dominant period from zero-crossings of a mean-removed signal."""
    x = x - np.mean(x)
    if len(x) < 4:
        return None
    signs = np.sign(x)
    signs[signs == 0] = 1
    diff = np.diff(signs)
    crossings = np.where(diff != 0)[0]
    if len(crossings) < 2:
        return None
    intervals = np.diff(crossings) / fs
    # Period = 2 × mean half-period
    return float(2.0 * np.mean(intervals))


def _welch_dominant(
    x: np.ndarray, fs: float, min_samples: int = 16
) -> Tuple[
    Optional[float], Optional[float], Optional[np.ndarray], Optional[np.ndarray]
]:
    """
    Compute Welch PSD for x sampled at fs Hz.

    Returns (dominant_freq, confidence, freqs, psd).
    confidence is based on peak-to-mean power ratio, normalised to [0, 1].
    DC component is excluded from peak search.
    """
    if len(x) < min_samples:
        return None, None, None, None

    nperseg = min(len(x) // 2, 64)
    nperseg = max(nperseg, 4)

    try:
        freqs, psd = scipy_signal.welch(x - np.mean(x), fs=fs, nperseg=nperseg)
    except Exception:
        return None, None, None, None

    if psd.sum() == 0:
        return None, 0.0, freqs, psd

    # Exclude DC (index 0)
    psd_no_dc = psd.copy()
    psd_no_dc[0] = 0.0

    if psd_no_dc.max() == 0:
        return None, 0.0, freqs, psd

    idx = int(np.argmax(psd_no_dc))
    dom_freq = float(freqs[idx])
    peak = float(psd_no_dc[idx])
    mean_power = float(psd_no_dc.mean()) + 1e-12
    # Normalise: confidence saturates at 10× peak-to-mean
    confidence = min(1.0, (peak / mean_power) / 10.0)

    return dom_freq, confidence, freqs, psd


def _spectral_entropy(psd: np.ndarray) -> float:
    """Shannon entropy of normalised PSD (nats)."""
    p = psd / (psd.sum() + 1e-12)
    p = p[p > 0]
    return float(-np.sum(p * np.log(p)))


def _spectral_energy_bands(
    freqs: np.ndarray,
    psd: np.ndarray,
    bands: List[Tuple[float, float]],
) -> Dict[str, float]:
    """Integrate PSD energy within each frequency band."""
    total = psd.sum() + 1e-12
    result = {}
    for lo, hi in bands:
        mask = (freqs >= lo) & (freqs < hi)
        label = f"{lo:.2f}-{hi:.2f}Hz"
        result[label] = float(psd[mask].sum() / total)
    return result


def _unwrap_angle(prev: Optional[float], curr: float) -> float:
    """Unwrap a single angle step to minimise discontinuity (radians)."""
    if prev is None:
        return curr
    diff = curr - prev
    # Wrap diff to (-π, π]
    diff = (diff + math.pi) % (2 * math.pi) - math.pi
    return prev + diff


def _moving_average(buf: Deque[float]) -> float:
    return float(np.mean(list(buf)))


# --------------------------------------------------------------------------- #
# Doppler correction: encounter frequency → true wave frequency               #
# --------------------------------------------------------------------------- #
# Reference: bareboat-necessities wave estimation math
# https://bareboat-necessities.github.io/my-bareboat/bareboat-math.html
#
# The boat moves through waves at speed STW.  The component of boat velocity
# along the wave propagation direction is:
#     delta_v = STW * cos(angle_between_heading_and_waves)
#
# For head seas delta_v > 0 (encounter freq > true freq);
# for following seas delta_v < 0 (encounter freq < true freq).
#
# The encounter frequency f_e relates to the true frequency f via the
# deep-water dispersion relation  ω² = g·k  and the Doppler shift:
#     ω_e = ω - k · delta_v          (ω = 2π·f, k = ω²/g)
#
# Solving for ω (true angular frequency) given ω_e and delta_v:
#     ω² · (delta_v / g) - ω + ω_e = 0
#
# This is a quadratic in ω.  For delta_v ≠ 0:
#     ω = [1 ± sqrt(1 - 4·(delta_v/g)·ω_e)] / [2·delta_v/g]
#
# We pick the physically meaningful root (positive ω, and the one closest
# to ω_e when delta_v is small).
#
# From true ω:
#     T_true = 2π / ω
#     L      = g·T² / (2π)          deep-water wavelength
#     c      = L / T = g·T / (2π)   phase velocity
# --------------------------------------------------------------------------- #

_GRAVITY = 9.80665  # m/s²


def doppler_correct(
    encounter_freq_hz: float,
    delta_v: float,
) -> Optional[Tuple[float, float, float]]:
    """
    Convert encounter frequency to true wave frequency via Doppler correction.

    Parameters
    ----------
    encounter_freq_hz : float
        Observed (encounter) frequency in Hz.
    delta_v : float
        Component of boat speed along wave direction (m/s).
        Positive for head seas, negative for following seas.

    Returns
    -------
    (true_period_s, wavelength_m, phase_speed_m_s) or None if correction
    is infeasible (discriminant < 0 or result is non-physical).
    """
    if encounter_freq_hz <= 0:
        return None

    omega_e = 2.0 * math.pi * encounter_freq_hz
    g = _GRAVITY

    # When delta_v ≈ 0 there is no Doppler shift
    if abs(delta_v) < 0.05:
        T = 1.0 / encounter_freq_hz
        L = g * T * T / (2.0 * math.pi)
        c = g * T / (2.0 * math.pi)
        return T, L, c

    # Forward Doppler: ω_e = ω + (ω²/g)·Δv   (head seas Δv > 0 → ω_e > ω)
    # Rearranged:      (Δv/g)·ω² + ω - ω_e = 0
    a_coeff = delta_v / g
    # a = Δv/g, b = 1, c = -ω_e
    discriminant = 1.0 + 4.0 * a_coeff * omega_e

    if discriminant < 0:
        # No real solution — correction infeasible (very strong following
        # sea or encounter freq too high for the speed)
        return None

    sqrt_disc = math.sqrt(discriminant)

    # Two roots: ω = (-1 ± √disc) / (2·Δv/g)
    omega_1 = (-1.0 + sqrt_disc) / (2.0 * a_coeff)
    omega_2 = (-1.0 - sqrt_disc) / (2.0 * a_coeff)

    # Pick the positive root that is physically meaningful
    candidates = []
    for omega in (omega_1, omega_2):
        if omega > 0:
            candidates.append(omega)

    if not candidates:
        return None

    # Prefer the root closest to omega_e (smallest Doppler shift)
    omega_true = min(candidates, key=lambda w: abs(w - omega_e))

    T = 2.0 * math.pi / omega_true
    L = g * T * T / (2.0 * math.pi)
    c = g * T / (2.0 * math.pi)

    # Sanity: reject non-physical results
    # True period should be positive and within ocean-wave range (1–30 s)
    if T < 1.0 or T > 30.0:
        return None

    return T, L, c


def compute_delta_v(
    stw: Optional[float],
    wind_angle_true: Optional[float],
) -> Optional[float]:
    """
    Estimate the component of boat speed along the wave propagation direction.

    Uses true wind angle as the best available proxy for wave direction
    (waves generally travel with the wind in wind-sea conditions).

    Parameters
    ----------
    stw : float or None
        Speed through water (m/s).
    wind_angle_true : float or None
        True wind angle relative to bow (rad). 0 = head wind, π = following.

    Returns
    -------
    delta_v in m/s or None if insufficient data.
    Positive = head seas (boat moves toward waves).
    Negative = following seas (boat moves with waves).
    """
    if stw is None or stw < 0.1:
        return None

    # Best case: we have true wind angle relative to bow
    if wind_angle_true is not None:
        # Wind angle 0 = wind from ahead → waves from ahead → head seas → delta_v > 0
        # Wind angle π = wind from astern → waves from astern → following → delta_v < 0
        # Waves travel in the same direction as wind, so the boat's velocity
        # component along the wave travel direction is STW * cos(wind_angle).
        # For wind_angle=0 (headwind): cos(0)=1, boat moves into waves → positive.
        return float(stw * math.cos(wind_angle_true))

    return None


def classify_wave_heading(
    delta_v: Optional[float], stw: Optional[float]
) -> Optional[str]:
    """
    Classify wave approach direction based on delta_v / STW ratio.

    Returns one of: head, following, beam, quartering_head, quartering_following,
    or None.
    """
    if delta_v is None or stw is None or stw < 0.1:
        return None

    ratio = delta_v / stw  # cos(angle between heading and wave direction)

    if ratio > 0.7:
        return "head"
    elif ratio > 0.3:
        return "quartering_head"
    elif ratio > -0.3:
        return "beam"
    elif ratio > -0.7:
        return "quartering_following"
    else:
        return "following"


# --------------------------------------------------------------------------- #
# Feature extractor                                                            #
# --------------------------------------------------------------------------- #


class FeatureExtractor:
    """
    Stateful feature extractor.  Call add_sample() at the configured sample
    rate.  The extractor maintains internal rolling buffers and returns
    layer-A features immediately.  Rolling window features and motion
    estimates are available via get_window_features() and get_motion_estimate().
    """

    def __init__(
        self,
        config: Config = DEFAULT_CONFIG,
        hull_params: Optional[Any] = None,
        learner: Optional[Any] = None,
    ) -> None:
        self._config = config
        self._fs = config.sample_rate_hz

        # Hull parameters for Phase 2 corrections (None = use defaults)
        self._hull_params: Optional[Any] = hull_params if _HULL_AVAILABLE else None

        # Online sea-state learner for Phase 3 (None = disabled)
        self._learner: Optional[Any] = learner if _LEARNER_AVAILABLE else None

        # Rolling sample buffers keyed by window size in seconds
        self._buffers: Dict[int, Deque[InstantSample]] = {
            w: deque(maxlen=int(w * self._fs)) for w in config.rolling_windows_s
        }

        # Previous-sample state for derivative computation
        self._prev_sample: Optional[InstantSample] = None
        self._prev_roll_uw: Optional[float] = None  # unwrapped
        self._prev_pitch_uw: Optional[float] = None
        self._prev_yaw_uw: Optional[float] = None

        # Derivative smoothing queues
        def _dq() -> Deque[float]:
            return deque(maxlen=config.derivative_filter_window)

        self._roll_rate_buf: Deque[float] = _dq()
        self._pitch_rate_buf: Deque[float] = _dq()
        self._yaw_rate_buf: Deque[float] = _dq()
        self._roll_acc_buf: Deque[float] = _dq()
        self._pitch_acc_buf: Deque[float] = _dq()

        self._prev_roll_rate: Optional[float] = None
        self._prev_pitch_rate: Optional[float] = None

        # Severity exponential smoothing state
        self._severity_smoothed: float = 0.0

        # Window period history for stability scoring
        self._roll_period_history: Dict[int, Deque[float]] = {
            w: deque(maxlen=5) for w in config.rolling_windows_s
        }
        self._pitch_period_history: Dict[int, Deque[float]] = {
            w: deque(maxlen=5) for w in config.rolling_windows_s
        }

        # Trend: severity history keyed by window
        self._severity_history: Deque[Tuple[datetime, float]] = deque(
            maxlen=int(30 * 60 * self._fs)
        )

        # Vertical acceleration buffer for wave estimation (separate from
        # the main rolling buffers because accel arrives at IMU sample rate,
        # not at the canonical 2 Hz sample rate).
        imu_fs = config.imu_sample_rate_hz
        self._accel_buf: Deque[float] = deque(maxlen=int(300 * imu_fs))
        self._accel_fs: float = imu_fs  # actual sample rate of accel data
        self._imu_highrate_active: bool = False  # set True on first add_imu_accel

        # Kalman heave estimator (if heave module available)
        self._kalman_heave: Optional[Any] = None
        self._latest_wave_estimate: Optional[Any] = None
        if _HEAVE_AVAILABLE:
            self._kalman_heave = KalmanHeaveEstimator(
                dt=1.0 / imu_fs,
                pos_integral_trans_var=config.heave_kalman_pos_integral_trans_var,
                pos_trans_var=config.heave_kalman_pos_trans_var,
                vel_trans_var=config.heave_kalman_vel_trans_var,
                pos_integral_obs_var=config.heave_kalman_pos_integral_obs_var,
                accel_bias_window=config.heave_kalman_bias_window,
            )

    # ------------------------------------------------------------------ #
    # Layer A                                                              #
    # ------------------------------------------------------------------ #

    def add_sample(self, sample: InstantSample) -> LayerAFeatures:
        """
        Ingest a new InstantSample.  Updates all rolling buffers and returns
        instantaneous derived features.
        """
        for buf in self._buffers.values():
            buf.append(sample)

        features = self._compute_layer_a(sample)
        self._prev_sample = sample

        # Buffer vertical_accel only when the high-rate IMU path is NOT
        # active, to avoid double-counting (50 Hz + 2 Hz → wrong PSD).
        if not self._imu_highrate_active and sample.vertical_accel is not None:
            self._accel_buf.append(sample.vertical_accel)

        return features

    def add_imu_accel(self, vertical_accel: float) -> None:
        """Buffer a single vertical acceleration sample from the IMU.

        Call this at IMU sample rate (e.g. 50 Hz), not at the canonical
        2 Hz sample rate.  This feeds the heave Kalman filter in real-time
        and accumulates data for periodic wave estimation.
        """
        self._imu_highrate_active = True
        self._accel_buf.append(vertical_accel)
        if self._kalman_heave is not None:
            self._kalman_heave.update(vertical_accel)

    def _compute_layer_a(self, sample: InstantSample) -> LayerAFeatures:
        now = sample.timestamp
        out = LayerAFeatures(timestamp=now)

        if self._prev_sample is None:
            # First sample – just unwrap angles and return empty derivatives
            if sample.roll is not None:
                self._prev_roll_uw = sample.roll
            if sample.pitch is not None:
                self._prev_pitch_uw = sample.pitch
            if sample.yaw is not None:
                self._prev_yaw_uw = sample.yaw
            return out

        dt = (now - self._prev_sample.timestamp).total_seconds()
        if dt <= 0:
            return out

        # ---- unwrap and differentiate roll ---- #
        if sample.roll is not None and self._prev_roll_uw is not None:
            roll_uw = _unwrap_angle(self._prev_roll_uw, sample.roll)
            raw_rate = (roll_uw - self._prev_roll_uw) / dt
            self._roll_rate_buf.append(raw_rate)
            smoothed_rate = _moving_average(self._roll_rate_buf)
            out.roll_rate = smoothed_rate
            self._prev_roll_uw = roll_uw

            if self._prev_roll_rate is not None:
                raw_acc = (smoothed_rate - self._prev_roll_rate) / dt
                self._roll_acc_buf.append(raw_acc)
                out.roll_acceleration = _moving_average(self._roll_acc_buf)
            self._prev_roll_rate = smoothed_rate
        elif sample.roll is not None:
            self._prev_roll_uw = sample.roll

        # ---- unwrap and differentiate pitch ---- #
        if sample.pitch is not None and self._prev_pitch_uw is not None:
            pitch_uw = _unwrap_angle(self._prev_pitch_uw, sample.pitch)
            raw_rate = (pitch_uw - self._prev_pitch_uw) / dt
            self._pitch_rate_buf.append(raw_rate)
            smoothed_rate = _moving_average(self._pitch_rate_buf)
            out.pitch_rate = smoothed_rate
            self._prev_pitch_uw = pitch_uw

            if self._prev_pitch_rate is not None:
                raw_acc = (smoothed_rate - self._prev_pitch_rate) / dt
                self._pitch_acc_buf.append(raw_acc)
                out.pitch_acceleration = _moving_average(self._pitch_acc_buf)
            self._prev_pitch_rate = smoothed_rate
        elif sample.pitch is not None:
            self._prev_pitch_uw = sample.pitch

        # ---- unwrap and differentiate yaw ---- #
        if sample.yaw is not None and self._prev_yaw_uw is not None:
            yaw_uw = _unwrap_angle(self._prev_yaw_uw, sample.yaw)
            raw_rate = (yaw_uw - self._prev_yaw_uw) / dt
            self._yaw_rate_buf.append(raw_rate)
            out.yaw_rate_derived = _moving_average(self._yaw_rate_buf)
            self._prev_yaw_uw = yaw_uw
        elif sample.yaw is not None:
            self._prev_yaw_uw = sample.yaw

        # ---- heading minus COG (leeway/drift proxy) ---- #
        if sample.heading is not None and sample.cog is not None:
            diff = sample.heading - sample.cog
            # Wrap to (-π, π]
            diff = (diff + math.pi) % (2 * math.pi) - math.pi
            out.heading_minus_cog = diff

        # ---- wind angles relative to bow (heading) ---- #
        heading_ref = sample.heading if sample.heading is not None else sample.cog
        if heading_ref is not None and sample.wind_angle_true is not None:
            out.wind_angle_true_bow = _angle_relative_to_bow(
                sample.wind_angle_true, heading_ref
            )
        if heading_ref is not None and sample.wind_angle_apparent is not None:
            out.wind_angle_apparent_bow = _angle_relative_to_bow(
                sample.wind_angle_apparent, heading_ref
            )

        # ---- speed-normalized roll / pitch ---- #
        if sample.roll is not None and sample.sog is not None and sample.sog > 0.5:
            out.roll_normalized = sample.roll / sample.sog
        if sample.pitch is not None and sample.sog is not None and sample.sog > 0.5:
            out.pitch_normalized = sample.pitch / sample.sog

        return out

    # ------------------------------------------------------------------ #
    # Layer B                                                              #
    # ------------------------------------------------------------------ #

    def get_window_features(self, window_s: int) -> Optional[WindowFeatures]:
        """Compute rolling-window statistics for the given window size."""
        buf = self._buffers.get(window_s)
        if buf is None or len(buf) < max(4, int(window_s * self._fs * 0.25)):
            return None

        samples = list(buf)
        n = len(samples)
        now = samples[-1].timestamp

        def _arr(attr: str) -> np.ndarray:
            vals = [getattr(s, attr) for s in samples if getattr(s, attr) is not None]
            return np.array(vals, dtype=float)

        roll = _arr("roll")
        pitch = _arr("pitch")
        rot = _arr("rate_of_turn")
        sog = _arr("sog")
        heading = _arr("heading")
        cog = _arr("cog")
        wst = _arr("wind_speed_true")
        wat = _arr("wind_angle_true")

        wf = WindowFeatures(timestamp=now, window_s=float(window_s), n_samples=n)

        # ---- roll stats ---- #
        if len(roll) >= 4:
            wf.roll_mean = float(np.mean(roll))
            wf.roll_std = float(np.std(roll))
            wf.roll_rms = _rms(roll)
            wf.roll_p2p = float(np.ptp(roll))
            wf.roll_kurtosis = float(scipy_kurtosis(roll, fisher=True))
            wf.roll_crest_factor = _crest_factor(roll)
            wf.roll_zero_crossing_period = _zero_crossing_period(roll, self._fs)

            dom_f, conf, freqs, psd = _welch_dominant(
                roll, self._fs, self._config.psd_min_samples
            )
            wf.roll_dominant_freq = dom_f
            wf.roll_period_confidence = conf
            if dom_f and dom_f > 0:
                wf.roll_dominant_period = 1.0 / dom_f
            if psd is not None and freqs is not None:
                wf.roll_spectral_energy = float(psd.sum())
                wf.spectral_entropy_roll = _spectral_entropy(psd)
                wf.spectral_bands_roll = _spectral_energy_bands(
                    freqs, psd, self._config.freq_bands
                )

            # Period stability
            if wf.roll_dominant_period is not None:
                self._roll_period_history[window_s].append(wf.roll_dominant_period)
            ph = list(self._roll_period_history[window_s])
            if len(ph) >= 2:
                wf.roll_period_stability = float(np.std(ph))

        # ---- pitch stats ---- #
        if len(pitch) >= 4:
            wf.pitch_mean = float(np.mean(pitch))
            wf.pitch_std = float(np.std(pitch))
            wf.pitch_rms = _rms(pitch)
            wf.pitch_p2p = float(np.ptp(pitch))
            wf.pitch_kurtosis = float(scipy_kurtosis(pitch, fisher=True))
            wf.pitch_crest_factor = _crest_factor(pitch)
            wf.pitch_zero_crossing_period = _zero_crossing_period(pitch, self._fs)

            dom_f, conf, freqs, psd = _welch_dominant(
                pitch, self._fs, self._config.psd_min_samples
            )
            wf.pitch_dominant_freq = dom_f
            wf.pitch_period_confidence = conf
            if dom_f and dom_f > 0:
                wf.pitch_dominant_period = 1.0 / dom_f
            if psd is not None and freqs is not None:
                wf.pitch_spectral_energy = float(psd.sum())
                wf.spectral_entropy_pitch = _spectral_entropy(psd)
                wf.spectral_bands_pitch = _spectral_energy_bands(
                    freqs, psd, self._config.freq_bands
                )

            if wf.pitch_dominant_period is not None:
                self._pitch_period_history[window_s].append(wf.pitch_dominant_period)
            ph = list(self._pitch_period_history[window_s])
            if len(ph) >= 2:
                wf.pitch_period_stability = float(np.std(ph))

        # ---- cross-signal variance ---- #
        if len(rot) >= 2:
            wf.yaw_rate_var = float(np.var(rot))
        if len(sog) >= 2:
            wf.sog_var = float(np.var(sog))
        if len(heading) >= 2 and len(cog) >= 2:
            min_len = min(len(heading), len(cog))
            diff = np.array(
                [_angle_wrap(h - c) for h, c in zip(heading[-min_len:], cog[-min_len:])]
            )
            wf.heading_cog_var = float(np.var(diff))
        if len(wst) >= 2:
            wf.wind_speed_var = float(np.var(wst))
        if len(wat) >= 2:
            wf.wind_angle_var = float(np.var(wat))
            # Circular mean of true wind angle relative to bow
            wf.wind_angle_mean = float(
                math.atan2(np.mean(np.sin(wat)), np.mean(np.cos(wat)))
            )

        # ---- STW statistics (for Doppler correction quality) ---- #
        stw_arr = _arr("stw")
        if len(stw_arr) >= 2:
            wf.stw_mean = float(np.mean(stw_arr))
            wf.stw_std = float(np.std(stw_arr))

        # ---- rudder angle statistics (for manoeuvre detection) ---- #
        rudder = _arr("rudder_angle")
        if len(rudder) >= 2:
            wf.rudder_angle_mean = float(np.mean(rudder))
            wf.rudder_angle_std = float(np.std(rudder))

        # ---- depth statistics (for deep-water validation) ---- #
        depth = _arr("depth")
        if len(depth) >= 1:
            wf.depth_mean = float(np.mean(depth))

        return wf

    # ------------------------------------------------------------------ #
    # Layer C                                                              #
    # ------------------------------------------------------------------ #

    def get_motion_estimate(
        self,
        window_s: int = 60,
        short_window_s: int = 10,
    ) -> Optional[MotionEstimate]:
        """
        Compute inferred wave-motion proxies from rolling-window features.

        These are inferences about vessel motion response only.
        """
        wf = self.get_window_features(window_s)
        if wf is None:
            return None

        now = wf.timestamp
        me = MotionEstimate(timestamp=now, window_s=float(window_s))

        # Record latest known position for downstream training joins.
        buf = self._buffers.get(window_s)
        if buf is not None and len(buf) > 0:
            latest = buf[-1]
            me.latitude = latest.latitude
            me.longitude = latest.longitude

        # ---- motion severity ---- #
        severity = self._compute_severity(wf)
        me.motion_severity = severity
        alpha = self._config.severity_smoothing_alpha
        self._severity_smoothed = (
            alpha * severity + (1 - alpha) * self._severity_smoothed
        )
        me.motion_severity_smoothed = self._severity_smoothed

        # Record for trend
        self._severity_history.append((now, severity))

        # ---- motion regime ---- #
        me.motion_regime = _regime_label(self._severity_smoothed)

        # ---- dominant periods ---- #
        me.dominant_roll_period = wf.roll_dominant_period
        me.dominant_pitch_period = wf.pitch_dominant_period
        roll_conf = wf.roll_period_confidence or 0.0
        pitch_conf = wf.pitch_period_confidence or 0.0
        me.period_confidence = float(max(roll_conf, pitch_conf))

        # Combined encounter period (weighted average if both present)
        rp = wf.roll_dominant_period
        pp = wf.pitch_dominant_period
        if rp and pp:
            # Weight by spectral energy
            re = wf.roll_spectral_energy or 1.0
            pe = wf.pitch_spectral_energy or 1.0
            me.encounter_period_estimate = (rp * re + pp * pe) / (re + pe)
        elif rp:
            me.encounter_period_estimate = rp
        elif pp:
            me.encounter_period_estimate = pp

        # ---- encounter direction proxy ---- #
        direction, dir_conf, roll_dom = _estimate_encounter_direction(wf)
        me.encounter_direction = direction
        me.direction_confidence = dir_conf
        me.roll_dominant = roll_dom

        # ---- Doppler correction: encounter period → true wave period ---- #
        self._apply_doppler_correction(me, wf)

        # ---- regularity / confusion ---- #
        me.confusion_index, me.motion_regularity = _estimate_regularity(wf)

        # ---- comfort proxy ---- #
        me.comfort_proxy = _comfort_proxy(wf, self._severity_smoothed)

        # ---- trend ---- #
        me.severity_trend = self._estimate_trend(now)

        # ---- overall confidence ---- #
        me.overall_confidence = _overall_confidence(wf, me, self._hull_params)

        # ---- wave height estimation from IMU accel data ---- #
        self._apply_wave_estimation(me, wf)

        # ---- Phase 3: online learning observation + correction ---- #
        self._apply_learned_correction(me)

        return me

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    def _apply_doppler_correction(self, me: MotionEstimate, wf: WindowFeatures) -> None:
        """
        Attempt Doppler correction on the encounter period estimate.

        Populates me.true_wave_period, me.true_wavelength, me.wave_speed,
        me.doppler_delta_v, me.doppler_correction_valid, and me.wave_heading.

        Requires: encounter_period_estimate, STW, and wind angle data in the
        rolling window.

        Validation guards:
        - Suppressed during manoeuvres (rudder_angle_std > threshold).
        - Flagged (but still computed) in shallow water where deep-water
          dispersion may not hold.
        """
        cfg = self._config
        me.doppler_correction_valid = False

        encounter_period = me.encounter_period_estimate
        if encounter_period is None or encounter_period <= 0:
            return

        encounter_freq = 1.0 / encounter_period

        # --- Guard: manoeuvre detection via rudder angle --- #
        if (
            wf.rudder_angle_std is not None
            and wf.rudder_angle_std > cfg.doppler_rudder_std_max
        ):
            logger.debug(
                "Doppler correction suppressed: rudder_angle_std=%.3f > %.3f",
                wf.rudder_angle_std,
                cfg.doppler_rudder_std_max,
            )
            return

        # --- Guard: minimum STW --- #
        if wf.stw_mean is not None and wf.stw_mean < cfg.doppler_min_stw:
            return

        # Compute mean delta_v from samples in the buffer
        buf = self._buffers.get(int(me.window_s))
        if buf is None or len(buf) < 4:
            return

        delta_vs: List[float] = []
        for s in buf:
            dv = compute_delta_v(s.stw, s.wind_angle_true)
            if dv is not None:
                delta_vs.append(dv)

        if len(delta_vs) < max(4, len(buf) // 4):
            # Not enough STW / wind data in the window
            return

        mean_delta_v = float(np.mean(delta_vs))
        me.doppler_delta_v = mean_delta_v

        # Classify wave heading from delta_v
        mean_stw = wf.stw_mean
        me.wave_heading = classify_wave_heading(mean_delta_v, mean_stw)

        # Apply Doppler correction
        result = doppler_correct(encounter_freq, mean_delta_v)
        if result is None:
            return

        true_period, wavelength, phase_speed = result
        me.true_wave_period = true_period
        me.true_wavelength = wavelength
        me.wave_speed = phase_speed

        # --- Shallow-water flag --- #
        # Deep-water assumption requires depth > wavelength / 2.
        # If depth data is available and too shallow, flag the result as
        # unreliable but still provide it.
        if wf.depth_mean is not None and wf.depth_mean > 0:
            if wf.depth_mean < wavelength / 2.0:
                logger.debug(
                    "Doppler correction in shallow water: depth=%.1f m < L/2=%.1f m",
                    wf.depth_mean,
                    wavelength / 2.0,
                )
                # Still provide the estimate but mark it as not fully valid
                me.doppler_correction_valid = False
                return

        me.doppler_correction_valid = True

    def _apply_wave_estimation(self, me: MotionEstimate, wf: WindowFeatures) -> None:
        """Estimate wave height from buffered vertical acceleration data.

        Uses both trochoidal and Kalman methods via the heave_estimator
        module.  Populates me.significant_height, me.heave,
        me.wave_height_method, me.wave_height_confidence, and
        me.accel_dominant_freq/period/confidence.

        Requires IMU accel data in self._accel_buf.  Gracefully returns
        if insufficient data or heave module unavailable.
        """
        if not _HEAVE_AVAILABLE:
            return

        accel_data = np.array(self._accel_buf, dtype=float)
        min_samples = self._config.heave_min_accel_samples
        if len(accel_data) < min_samples:
            return

        # Use the last N seconds of accel data matching the motion estimate window
        window_samples = int(me.window_s * self._accel_fs)
        if len(accel_data) > window_samples:
            accel_data = accel_data[-window_samples:]

        # Compute delta_v from Doppler if available
        delta_v = me.doppler_delta_v or 0.0

        # Run combined wave estimation
        # NOTE: Do NOT pass the Kalman estimator here — it is already being
        # updated in real-time via add_imu_accel().  We just query its state.
        wave_est = estimate_waves_from_accel(
            vertical_accel=accel_data,
            fs=self._accel_fs,
            delta_v=delta_v,
            kalman_estimator=None,  # Kalman fed separately at IMU rate
            lowpass_cutoff_mult=self._config.heave_lowpass_cutoff_mult,
            psd_min_samples=min_samples,
            freq_min_hz=self._config.heave_freq_min_hz,
            freq_max_hz=self._config.heave_freq_max_hz,
            trochoidal_min_amplitude=self._config.heave_trochoidal_min_amplitude,
            hull_params=self._hull_params if _HULL_AVAILABLE else None,
        )

        # Overlay Kalman heave results if the filter has converged
        if self._kalman_heave is not None:
            kalman_est = self._kalman_heave.get_estimate(min_samples=min_samples)
            if kalman_est is not None:
                wave_est.kalman = kalman_est
                wave_est.heave = kalman_est.heave_displacement
                # If trochoidal also produced a result, compare
                if wave_est.trochoidal is not None and kalman_est.converged:
                    hs_k = kalman_est.significant_height
                    hs_t = wave_est.trochoidal.significant_height
                    ratio = hs_k / (hs_t + 1e-6)
                    if 0.3 < ratio < 3.0:
                        # Agreement → use Kalman
                        wave_est.significant_height = hs_k
                        wave_est.method_used = "kalman"
                    # Otherwise keep trochoidal (already set)
                elif wave_est.significant_height is None:
                    # Only Kalman available — use it even before full
                    # convergence (useful immediately, bias stabilises later).
                    # Mark confidence lower when not yet converged.
                    wave_est.significant_height = kalman_est.significant_height
                    wave_est.method_used = "kalman"
                    if not kalman_est.converged:
                        wave_est.confidence = (
                            min(wave_est.confidence, 0.3)
                            if wave_est.confidence > 0
                            else 0.3
                        )
        self._latest_wave_estimate = wave_est

        # Log wave estimation result
        logger.debug(
            "wave_est: samples=%d, accel_rms=%.4f, freq=%.3f, "
            "troch=%s, kalman=%s, spectral=%s, Hs=%s, method=%s, accel_max=%.4f",
            len(accel_data),
            wave_est.accel_rms or 0.0,
            wave_est.accel_dominant_freq or 0.0,
            f"{wave_est.trochoidal.significant_height:.3f}"
            if wave_est.trochoidal
            else "None",
            f"{wave_est.kalman.significant_height:.3f}" if wave_est.kalman else "None",
            f"{wave_est.spectral_hs:.3f}"
            if wave_est.spectral_hs is not None
            else "None",
            f"{wave_est.significant_height:.3f}"
            if wave_est.significant_height is not None
            else "None",
            wave_est.method_used,
            wave_est.accel_max or 0.0,
        )

        # Populate MotionEstimate fields
        if wave_est.significant_height is not None:
            me.significant_height = round(wave_est.significant_height, 3)
        if wave_est.heave is not None:
            me.heave = round(wave_est.heave, 3)
        me.wave_height_method = wave_est.method_used
        if wave_est.confidence > 0:
            me.wave_height_confidence = round(wave_est.confidence, 3)
        if wave_est.accel_dominant_freq is not None:
            me.accel_dominant_freq = round(wave_est.accel_dominant_freq, 4)
        if wave_est.accel_dominant_period is not None:
            me.accel_dominant_period = round(wave_est.accel_dominant_period, 2)
        if wave_est.accel_freq_confidence is not None:
            me.accel_freq_confidence = round(wave_est.accel_freq_confidence, 3)

        # Populate partition-level spectral wave features.
        if wave_est.spectral_partitions:
            for part in wave_est.spectral_partitions:
                if part.component_type == "wind_wave":
                    me.wind_wave_height = round(part.hs_m, 3)
                    me.wind_wave_period = round(part.peak_period_s, 2)
                    me.wind_wave_freq = round(part.peak_freq_hz, 4)
                    me.wind_wave_confidence = round(part.confidence, 3)
                elif part.component_type == "swell_1":
                    me.swell_1_height = round(part.hs_m, 3)
                    me.swell_1_period = round(part.peak_period_s, 2)
                    me.swell_1_freq = round(part.peak_freq_hz, 4)
                    me.swell_1_confidence = round(part.confidence, 3)
                elif part.component_type == "swell_2":
                    me.swell_2_height = round(part.hs_m, 3)
                    me.swell_2_period = round(part.peak_period_s, 2)
                    me.swell_2_freq = round(part.peak_freq_hz, 4)
                    me.swell_2_confidence = round(part.confidence, 3)

        # RAO correction: if hull parameters are available, correct Hs for
        # hull amplification/attenuation at the observed wave period.
        self._apply_rao_correction(me)

    def _apply_rao_correction(self, me: MotionEstimate) -> None:
        """Apply RAO gain correction to wave height and adjust confidence.

        If hull parameters are available, determines the RAO gain at the
        observed wave period and divides Hs by the gain (removing hull
        amplification).  Also adjusts wave_height_confidence using the
        rao_confidence_adjustment helper.

        Populates ``me.rao_gain_applied`` for logging/debugging.
        """
        if not _HULL_AVAILABLE or self._hull_params is None:
            return
        if me.significant_height is None:
            return

        # Best available period: prefer true (Doppler-corrected), then
        # accel-derived encounter period, then attitude-derived estimate.
        period = (
            me.true_wave_period
            or me.accel_dominant_period
            or me.encounter_period_estimate
        )
        if period is None or period <= 0:
            return

        gain = rao_gain(period, self._hull_params)
        me.rao_gain_applied = round(gain, 4)

        # Correct significant height: divide out hull amplification
        me.significant_height = round(me.significant_height / gain, 3)

        # Adjust wave height confidence
        _period_boost, hs_penalty = rao_confidence_adjustment(period, self._hull_params)
        if me.wave_height_confidence is not None:
            me.wave_height_confidence = round(
                float(np.clip(me.wave_height_confidence * hs_penalty, 0.0, 1.0)),
                3,
            )

    def _apply_learned_correction(self, me: MotionEstimate) -> None:
        """Phase 3: observe + apply learned vessel-specific correction.

        1. Feed the current estimate into the learner for accumulation.
        2. If the learner has sufficient data, apply its correction factor
           to significant_height.

        The learner correction is multiplicative on top of the RAO correction
        (Phase 2).  It captures vessel-specific deviations from the generic
        RAO model.
        """
        if not _LEARNER_AVAILABLE or self._learner is None:
            return

        # Best available period for bin selection
        period = (
            me.true_wave_period
            or me.accel_dominant_period
            or me.encounter_period_estimate
        )

        # Observe (accumulate into bin)
        self._learner.observe(
            wave_period=period,
            encounter_direction=me.encounter_direction,
            motion_severity=me.motion_severity_smoothed,
            significant_height=me.significant_height,
        )

        # Apply learned correction to Hs if available
        if me.significant_height is not None and period is not None:
            factor = self._learner.correction_factor(
                wave_period=period,
                encounter_direction=me.encounter_direction,
            )
            if factor != 1.0:
                me.significant_height = round(me.significant_height * factor, 3)
                logger.debug(
                    "Learned correction: period=%.1fs dir=%s factor=%.3f",
                    period,
                    me.encounter_direction,
                    factor,
                )

    def _compute_severity(self, wf: WindowFeatures) -> float:
        cfg = self._config
        hp = self._hull_params
        scores: Dict[str, float] = {}

        # Use hull-type-specific max thresholds if available, else config defaults
        if hp is not None and hp.severity_max_overrides:
            roll_rms_max = hp.severity_max_overrides.get(
                "severity_roll_rms_max", cfg.severity_roll_rms_max
            )
            pitch_rms_max = hp.severity_max_overrides.get(
                "severity_pitch_rms_max", cfg.severity_pitch_rms_max
            )
            roll_spectral_max = hp.severity_max_overrides.get(
                "severity_roll_spectral_max", cfg.severity_roll_spectral_max
            )
            yaw_rate_var_max = hp.severity_max_overrides.get(
                "severity_yaw_rate_var_max", cfg.severity_yaw_rate_var_max
            )
        else:
            roll_rms_max = cfg.severity_roll_rms_max
            pitch_rms_max = cfg.severity_pitch_rms_max
            roll_spectral_max = cfg.severity_roll_spectral_max
            yaw_rate_var_max = cfg.severity_yaw_rate_var_max

        if wf.roll_rms is not None:
            scores["roll_rms"] = min(1.0, wf.roll_rms / roll_rms_max)
        if wf.pitch_rms is not None:
            scores["pitch_rms"] = min(1.0, wf.pitch_rms / pitch_rms_max)
        if wf.roll_spectral_energy is not None:
            scores["roll_spectral"] = min(
                1.0, wf.roll_spectral_energy / roll_spectral_max
            )
        if wf.yaw_rate_var is not None:
            scores["yaw_rate_var"] = min(1.0, wf.yaw_rate_var / yaw_rate_var_max)

        if not scores:
            return 0.0

        # Use hull-type-specific weights if available, else config defaults
        weights = (
            hp.severity_weights
            if hp is not None and hp.severity_weights
            else cfg.severity_weights
        )

        total_weight = sum(weights.get(k, 0.0) for k in scores)
        if total_weight == 0:
            return 0.0

        weighted = sum(scores[k] * weights.get(k, 0.0) for k in scores)
        return float(weighted / total_weight)

    def _estimate_trend(self, now: datetime) -> str:
        hist = list(self._severity_history)
        if len(hist) < 10:
            return "stable"

        def _mean_in_last(seconds: float) -> Optional[float]:
            cutoff = now.timestamp() - seconds
            vals = [v for t, v in hist if t.timestamp() >= cutoff]
            return float(np.mean(vals)) if vals else None

        short = _mean_in_last(5 * 60)
        medium = _mean_in_last(15 * 60)
        long_ = _mean_in_last(30 * 60)

        if short is None or medium is None:
            return "stable"

        ref = long_ if long_ is not None else medium
        delta = short - ref
        if abs(delta) < 0.05:
            return "stable"
        return "worsening" if delta > 0 else "improving"

    # ------------------------------------------------------------------ #
    # Accessors                                                             #
    # ------------------------------------------------------------------ #

    def buffer_fill(self, window_s: int) -> int:
        """Number of samples in the given window buffer."""
        return len(self._buffers.get(window_s, deque()))

    def buffer_capacity(self, window_s: int) -> int:
        buf = self._buffers.get(window_s)
        return buf.maxlen if buf is not None else 0


# --------------------------------------------------------------------------- #
# Module-level heuristic functions                                             #
# --------------------------------------------------------------------------- #


def _angle_relative_to_bow(angle_abs: float, heading: float) -> float:
    """Convert an absolute wind angle (rad) to angle relative to bow."""
    rel = angle_abs - heading
    return _angle_wrap(rel)


def _angle_wrap(a: float) -> float:
    """Wrap angle to (-π, π]."""
    return (a + math.pi) % (2 * math.pi) - math.pi


def _regime_label(severity: float) -> str:
    if severity < 0.2:
        return "calm"
    elif severity < 0.45:
        return "moderate"
    elif severity < 0.70:
        return "active"
    else:
        return "heavy"


def _estimate_encounter_direction(
    wf: WindowFeatures,
) -> Tuple[str, float, bool]:
    """
    Infer encounter direction proxy from wind angle and spectral energy.

    Uses wind angle as the primary directional signal (when available),
    with roll/pitch spectral energy ratio and yaw variance as secondary
    confirmation.

    Labels returned:
        head_like            – waves from ahead (wind angle |α| < 30°)
        head_quartering_like – waves from forward quarter (30° ≤ |α| < 60°)
        beam_like            – waves abeam (60° ≤ |α| < 120°)
        following_quartering_like – waves from aft quarter (120° ≤ |α| < 150°)
        following_like       – waves from astern (|α| ≥ 150°)
        confused_like        – high confusion index, no clear direction
        unknown              – insufficient data

    When wind angle is not available, falls back to spectral energy ratio
    with the legacy head_or_following_like / beam_like / quartering_like
    labels.

    Returns (label, confidence, roll_dominant).
    """
    re = wf.roll_spectral_energy or 0.0
    pe = wf.pitch_spectral_energy or 0.0
    total = re + pe

    if total < 1e-8:
        return "unknown", 0.0, False

    roll_dom = re > pe
    ratio = (re - pe) / total  # -1 = pure pitch, +1 = pure roll
    yaw_var = wf.yaw_rate_var or 0.0

    # Base confidence on energy level
    base_conf = min(1.0, math.sqrt(total) / 0.05)

    wind_angle = wf.wind_angle_mean  # rad, relative to bow, signed

    if wind_angle is not None:
        # --- Primary path: wind-angle-based classification --- #
        # |α| gives angle off the bow regardless of port/starboard.
        abs_angle = abs(wind_angle)  # 0 = head, π = following

        # Determine if spectral data is consistent with the wind angle.
        # Pitch-dominant (ratio < -0.2) is consistent with head or following.
        # Roll-dominant (ratio > 0.2) is consistent with beam or quartering.
        # The "dead zone" ratio in [-0.2, 0.2] is consistent with anything.
        spectral_consistent = True
        if abs_angle < math.radians(45):
            # Wind says head-ish; pitch should dominate or be balanced
            spectral_consistent = ratio < 0.3
        elif abs_angle > math.radians(135):
            # Wind says following-ish; pitch should dominate or be balanced
            spectral_consistent = ratio < 0.3
        elif math.radians(70) < abs_angle < math.radians(110):
            # Wind says beam-ish; roll should dominate or be balanced
            spectral_consistent = ratio > -0.3

        # Confidence boost when spectral data agrees with wind angle
        conf_mult = 0.9 if spectral_consistent else 0.65

        # High wind angle variance degrades confidence (shifting wind)
        if wf.wind_angle_var is not None and wf.wind_angle_var > 0.3:
            conf_mult *= 0.7

        # Classify by wind angle sector
        #   0°–30°   = head (wind from ahead)
        #  30°–60°   = head quartering
        #  60°–120°  = beam
        # 120°–165°  = following quartering (includes the dangerous
        #              aft-quarter zone sailors care about most)
        # 165°–180°  = dead following (wind from astern)
        if abs_angle < math.radians(30):
            label = "head_like"
        elif abs_angle < math.radians(60):
            label = "head_quartering_like"
        elif abs_angle < math.radians(120):
            label = "beam_like"
        elif abs_angle < math.radians(165):
            label = "following_quartering_like"
        else:
            label = "following_like"

        # Confusion override: if spectral regularity is very low,
        # upgrade to confused regardless of wind angle.
        confusion, _ = _estimate_regularity(wf)
        if confusion > 0.7 and not spectral_consistent:
            label = "confused_like"
            conf_mult = 0.4

        confidence = base_conf * conf_mult
        return label, float(np.clip(confidence, 0.0, 1.0)), roll_dom

    # --- Fallback: spectral-only classification (no wind angle) --- #
    # Improved over old version: use yaw variance to disambiguate
    # quartering in the mixed zone too.
    if ratio > 0.4:
        # Strong roll
        if yaw_var > 0.001:
            label = "quartering_like"
            confidence = base_conf * 0.7
        else:
            label = "beam_like"
            confidence = base_conf * 0.8
    elif ratio < -0.4:
        # Strong pitch — cannot distinguish head from following without
        # wind angle, but yaw variance hints at quartering tendency.
        if yaw_var > 0.002:
            label = "quartering_like"
            confidence = base_conf * 0.55
        else:
            label = "head_or_following_like"
            confidence = base_conf * 0.6
    else:
        # Balanced energy
        confusion, _ = _estimate_regularity(wf)
        if yaw_var > 0.001:
            label = "quartering_like"
            confidence = base_conf * 0.5
        elif confusion > 0.5:
            label = "confused_like"
            confidence = base_conf * 0.4
        else:
            label = "mixed"
            confidence = base_conf * 0.4

    return label, float(np.clip(confidence, 0.0, 1.0)), roll_dom


def _estimate_regularity(wf: WindowFeatures) -> Tuple[float, str]:
    """
    Return (confusion_index 0–1, label).
    """
    scores: List[float] = []

    # Spectral entropy: high = confused
    se_roll = wf.spectral_entropy_roll
    se_pitch = wf.spectral_entropy_pitch
    if se_roll is not None and se_pitch is not None:
        # Normalise by log(n_freq) for the nperseg used; use a rough scale
        entropy_norm = min(1.0, (se_roll + se_pitch) / 10.0)
        scores.append(entropy_norm)

    # Period instability
    if wf.roll_period_stability is not None:
        # Normalise by 5s (high instability = confused)
        scores.append(min(1.0, wf.roll_period_stability / 5.0))
    if wf.pitch_period_stability is not None:
        scores.append(min(1.0, wf.pitch_period_stability / 5.0))

    if not scores:
        return 0.5, "unknown"

    confusion = float(np.mean(scores))
    if confusion < 0.30:
        label = "regular"
    elif confusion < 0.60:
        label = "mixed"
    else:
        label = "confused"

    return confusion, label


def _comfort_proxy(wf: WindowFeatures, severity_smoothed: float) -> float:
    """Simple comfort proxy 0 (comfortable) to 1 (very uncomfortable)."""
    # Blend severity with crest factor penalty
    cf_roll = wf.roll_crest_factor or 1.4
    cf_pitch = wf.pitch_crest_factor or 1.4
    cf_penalty = min(1.0, (max(cf_roll, cf_pitch) - 1.0) / 4.0)
    return float(np.clip(0.7 * severity_smoothed + 0.3 * cf_penalty, 0.0, 1.0))


def _overall_confidence(
    wf: WindowFeatures,
    me: MotionEstimate,
    hull_params: Optional[Any] = None,
) -> float:
    """Heuristic overall confidence 0–1 based on data completeness.

    When hull_params is provided, applies resonance-aware adjustments:
    - Period confidence boosted when dominant period is near natural period
    - Wave height confidence penalised when near hull resonance (amplified)
    """
    checks = [
        wf.roll_rms is not None,
        wf.pitch_rms is not None,
        wf.roll_dominant_period is not None,
        wf.pitch_dominant_period is not None,
        (wf.roll_period_confidence or 0) > 0.3,
        (wf.pitch_period_confidence or 0) > 0.3,
    ]
    base = float(sum(checks)) / len(checks)

    # Penalise high confusion
    confusion = me.confusion_index or 0.5
    penalised = base * (1.0 - 0.4 * confusion)

    # Resonance-aware adjustments
    if hull_params is not None and _HULL_AVAILABLE:
        period = me.encounter_period_estimate
        if period is not None and period > 0:
            period_boost, hs_penalty = rao_confidence_adjustment(period, hull_params)
            # Boost overall confidence if period is near natural period
            # (vessel responds strongly = clear signal for detection)
            penalised *= period_boost

    return float(np.clip(penalised, 0.0, 1.0))
