"""Heave and wave height estimation from IMU vertical acceleration.

Implements two complementary methods from the bareboat-necessities reference:
  https://bareboat-necessities.github.io/my-bareboat/bareboat-math.html

1. **Trochoidal wave height** -- reconstruct wave amplitude from max/min
   vertical acceleration + observed frequency.  No integration required.

2. **Kalman filter heave** -- double-integrate vertical acceleration into
   displacement with zero-mean drift correction.  Uses the third-integral
   trick from Sharkh et al. (2014): the observation is always 0 (because
   mean displacement over a wave cycle is zero), which prevents the
   inevitable drift of naive double integration.

Both methods require a known wave frequency.  The encounter frequency comes
from the Welch PSD already computed in the feature extractor; optionally a
Doppler-corrected true frequency can be substituted.

Constants and sign conventions
------------------------------
- ``vertical_accel`` is z-axis acceleration minus gravity (m/s^2).
  Positive = upward acceleration above 1g; negative = below 1g.
- All displacements and heights are in metres.
- ``GRAVITY = 9.80665 m/s^2`` (standard gravity).

References
----------
[1] Sharkh S.M. et al., "A Novel Kalman Filter Based Technique for
    Calculating the Time History of Vertical Displacement of a Boat
    from Measured Acceleration", Marine Engineering Frontiers, Vol 2, 2014.
[2] bareboat-necessities math reference (see URL above).
"""
from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Deque, Optional, Tuple

import numpy as np
from scipy import signal as scipy_signal

if TYPE_CHECKING:
    from vessel_config import HullParameters

logger = logging.getLogger(__name__)

GRAVITY = 9.80665  # m/s^2


# --------------------------------------------------------------------------- #
# Trochoidal wave height estimation                                            #
# --------------------------------------------------------------------------- #

@dataclass
class TrochoidalEstimate:
    """Result of trochoidal wave height estimation."""
    significant_height: float   # metres (Hs ~ 4 * std(heave) ~ 2 * amplitude for regular waves)
    wave_amplitude: float       # metres (H in trochoidal model -- half crest-to-trough)
    wavelength: float           # metres (L)
    wave_speed: float           # m/s (phase velocity, deep-water)
    b_parameter: float          # metres (rotation centre depth, always <= 0)
    accel_max: float            # m/s^2 (peak upward accel used)
    frequency_hz: float         # Hz (frequency used for computation)
    method: str = "trochoidal"


def trochoidal_wave_height(
    accel_max_observed: float,
    frequency_hz: float,
    delta_v: float = 0.0,
    min_amplitude: float = 0.005,
) -> Optional[TrochoidalEstimate]:
    """Estimate wave height from peak vertical acceleration and frequency.

    Uses the trochoidal wave model where vertical acceleration amplitude
    relates to wave geometry through:

        a_observed_max = H * k^2 * (c + delta_v)^2

    For zero delta_v (stationary or beam seas) this simplifies to:

        a_max = g * exp(2*pi*b / L)

    Parameters
    ----------
    accel_max_observed : float
        Peak magnitude of vertical acceleration (m/s^2), should be
        positive (absolute value of the largest excursion from zero).
    frequency_hz : float
        Observed (encounter) frequency in Hz.
    delta_v : float
        Boat velocity component along wave direction (m/s).
        Positive = head seas.  Default 0.
    min_amplitude : float
        Minimum wave amplitude (m) to consider physically real.

    Returns
    -------
    TrochoidalEstimate or None if inputs are invalid.
    """
    if frequency_hz <= 0.02 or frequency_hz > 2.0:
        # Outside plausible ocean wave range (~0.5 s to 50 s period)
        return None
    if accel_max_observed <= 0.01:
        # Negligible acceleration
        return None

    g = GRAVITY

    # Step 1: Compute source wavelength from observed frequency + delta_v
    # Using the Doppler formula from bareboat-necessities:
    #   L = (sign(dv) * sqrt(8*pi*f_o*g*dv + g^2) + 4*pi*f_o*dv + g) / (4*pi*f_o^2)
    # For delta_v = 0:  L = g / (4*pi*f_o^2) ... wait, that's wrong.
    # Actually for delta_v=0: f_o = f = c/L, c = sqrt(gL/(2pi))
    # => f = sqrt(g/(2*pi*L)) / 1  => L = g/(2*pi*f^2)
    # Let's use the general formula properly.

    f_o = frequency_hz
    doppler_applied = False

    if abs(delta_v) < 0.05:
        # No Doppler: L = g * T^2 / (2*pi) = g / (2*pi*f^2)
        wavelength = g / (2.0 * math.pi * f_o * f_o)
    else:
        # General Doppler formula from bareboat-necessities:
        discriminant = 8.0 * math.pi * f_o * g * delta_v + g * g
        if discriminant < 0:
            # Infeasible Doppler -- strong following sea makes the
            # quadratic have no real root.  Fall back to the no-Doppler
            # wavelength estimate (uses encounter frequency directly).
            # This overestimates wavelength in following seas but is far
            # better than returning None.
            logger.debug(
                "trochoidal Doppler infeasible (discriminant=%.1f, "
                "delta_v=%.2f, f=%.3f Hz); falling back to no-Doppler",
                discriminant, delta_v, f_o,
            )
            wavelength = g / (2.0 * math.pi * f_o * f_o)
        else:
            sign_dv = 1.0 if delta_v >= 0 else -1.0
            wavelength = (
                sign_dv * math.sqrt(discriminant)
                + 4.0 * math.pi * f_o * delta_v
                + g
            ) / (4.0 * math.pi * f_o * f_o)
            doppler_applied = True

    if wavelength <= 0.5:
        # Non-physical: wavelength too short
        return None

    # Step 2: Deep-water wave speed
    wave_speed = math.sqrt(g * wavelength / (2.0 * math.pi))

    # Step 3: Wavenumber
    k = 2.0 * math.pi / wavelength

    # Step 4: Correct observed accel to source accel if delta_v != 0.
    # Only apply when Doppler wavelength succeeded — the acceleration
    # correction uses the same Doppler model, so if the model failed
    # for wavelength we must skip it here too.
    c = wave_speed
    if doppler_applied:
        effective_speed = c + delta_v
        if abs(effective_speed) < 0.1:
            return None  # Near-stationary encounter
        a_max = accel_max_observed * (c * c) / (effective_speed * effective_speed)
    else:
        a_max = accel_max_observed

    # Step 5: Compute b parameter
    # a_max = g * exp(2*pi*b/L)
    # b = L/(2*pi) * ln(a_max/g)
    ratio = a_max / g
    if ratio <= 0 or ratio > 1.0:
        # ratio > 1 is impossible in trochoidal model (would mean b > 0)
        # ratio <= 0 is non-physical
        # For ratio very close to 1, wave is at breaking limit
        if ratio > 1.0:
            ratio = 1.0  # Clamp to breaking limit (b=0)
        else:
            return None

    b = wavelength / (2.0 * math.pi) * math.log(ratio)  # b <= 0

    # Step 6: Wave amplitude (half crest-to-trough)
    # H = L/(2*pi) * exp(2*pi*b/L)  = 1/k * exp(k*b)
    amplitude = math.exp(k * b) / k

    # Step 7: Validate
    max_amplitude = wavelength / (2.0 * math.pi)  # breaking limit
    if amplitude > max_amplitude:
        amplitude = max_amplitude  # clamp

    if amplitude < min_amplitude:
        # Below minimum threshold -- not a real wave
        return None

    # Significant wave height: for a regular monochromatic trochoidal wave,
    # Hs ~ 2 * amplitude (crest-to-trough = 2H, and Hs ~ crest-to-trough
    # for regular waves).  For irregular seas Hs = 4*std(surface).
    # We report 2*amplitude as a simple estimate.
    significant_height = 2.0 * amplitude

    method = "trochoidal" if (doppler_applied or abs(delta_v) < 0.05) else "trochoidal_no_doppler"
    return TrochoidalEstimate(
        significant_height=significant_height,
        wave_amplitude=amplitude,
        wavelength=wavelength,
        wave_speed=wave_speed,
        b_parameter=b,
        accel_max=a_max,
        frequency_hz=frequency_hz,
        method=method,
    )


# --------------------------------------------------------------------------- #
# Kalman filter heave estimator                                                #
# --------------------------------------------------------------------------- #

@dataclass
class HeaveState:
    """Current Kalman filter state for heave estimation."""
    displacement: float       # metres (current heave displacement)
    velocity: float           # m/s (current vertical velocity)
    displacement_integral: float  # m*s (third integral -- should stay near 0)


@dataclass
class HeaveEstimate:
    """Result from the Kalman heave estimator over a window."""
    heave_displacement: float     # metres (current heave)
    heave_amplitude: float        # metres (half peak-to-peak over window)
    significant_height: float     # metres (4 * std of heave over window)
    heave_std: float              # metres (standard deviation of heave)
    heave_max: float              # metres (max displacement in window)
    heave_min: float              # metres (min displacement in window)
    n_samples: int                # number of accel samples processed
    converged: bool               # whether the filter has likely converged
    method: str = "kalman"


class KalmanHeaveEstimator:
    """Online Kalman filter for heave displacement from vertical acceleration.

    Implements the Sharkh et al. (2014) method:
    - State: [displacement_integral, displacement, velocity]
    - Transition: Newtonian kinematics (dt, dt^2/2, dt^3/6)
    - Observation: displacement_integral = 0 (zero-mean constraint)
    - Transition offset: acceleration (bias-removed)

    The key insight is that average heave displacement over a wave cycle
    is zero.  By observing the *third integral* of acceleration (which
    should be zero on average), the filter corrects for integration drift.

    Parameters
    ----------
    dt : float
        Time step between samples (seconds).
    pos_integral_trans_var : float
        Process noise for displacement integral state.
    pos_trans_var : float
        Process noise for displacement state.
    vel_trans_var : float
        Process noise for velocity state.
    pos_integral_obs_var : float
        Observation noise for the zero-integral measurement.
    accel_bias_window : int
        Number of samples for running bias estimate.
    """

    def __init__(
        self,
        dt: float = 0.02,   # 50 Hz default
        pos_integral_trans_var: float = 1e-6,
        pos_trans_var: float = 1e-4,
        vel_trans_var: float = 1e-2,
        pos_integral_obs_var: float = 1e-1,
        accel_bias_window: int = 500,
    ) -> None:
        self._dt = dt
        self._accel_bias_window = accel_bias_window

        # Kalman matrices (3-state: [integral_of_displacement, displacement, velocity])
        dt2 = dt * dt
        dt3 = dt2 * dt

        # State transition matrix F
        self._F = np.array([
            [1.0, dt,  0.5 * dt2],
            [0.0, 1.0, dt],
            [0.0, 0.0, 1.0],
        ])

        # Transition offset vector B (multiplied by accel input)
        self._B = np.array([
            dt3 / 6.0,
            0.5 * dt2,
            dt,
        ])

        # Observation matrix H: we observe displacement_integral (index 0)
        self._H = np.array([[1.0, 0.0, 0.0]])

        # Process noise Q
        self._Q = np.diag([
            pos_integral_trans_var,
            pos_trans_var,
            vel_trans_var,
        ])

        # Observation noise R
        self._R = np.array([[pos_integral_obs_var]])

        # State estimate and covariance
        self._x = np.array([0.0, 0.0, 0.0])  # [integral, displacement, velocity]
        self._P = np.diag([pos_integral_obs_var, 1.0, 1.0])

        # Running bias estimate
        self._accel_buf: Deque[float] = deque(maxlen=accel_bias_window)
        self._accel_bias: float = 0.0

        # Heave history for statistics
        self._heave_history: Deque[float] = deque(maxlen=int(300 / dt))  # 5 min
        self._n_processed: int = 0

    def reset(
        self,
        initial_displacement: float = 0.0,
        initial_velocity: float = 0.0,
    ) -> None:
        """Reset filter state (e.g. after detecting a regime change)."""
        self._x = np.array([0.0, initial_displacement, initial_velocity])
        self._P = np.diag([self._R[0, 0], 1.0, 1.0])
        self._accel_buf.clear()
        self._accel_bias = 0.0
        self._heave_history.clear()
        self._n_processed = 0

    def update(self, vertical_accel: float) -> float:
        """Process one vertical acceleration sample.

        Parameters
        ----------
        vertical_accel : float
            Vertical acceleration in m/s^2, with gravity already removed
            (i.e. 0 when stationary).

        Returns
        -------
        Current heave displacement estimate in metres.
        """
        # Update running bias estimate
        self._accel_buf.append(vertical_accel)
        if len(self._accel_buf) >= 10:
            self._accel_bias = float(np.mean(self._accel_buf))

        # Bias-corrected acceleration
        accel_corrected = vertical_accel - self._accel_bias

        # === Kalman predict === #
        x_pred = self._F @ self._x + self._B * accel_corrected
        P_pred = self._F @ self._P @ self._F.T + self._Q

        # === Kalman update === #
        # Observation: displacement_integral should be 0
        y = 0.0 - self._H @ x_pred  # innovation
        S = self._H @ P_pred @ self._H.T + self._R  # innovation covariance
        K = P_pred @ self._H.T @ np.linalg.inv(S)  # Kalman gain

        self._x = x_pred + (K @ y).flatten()
        I = np.eye(3)
        self._P = (I - K @ self._H) @ P_pred

        displacement = float(self._x[1])
        self._heave_history.append(displacement)
        self._n_processed += 1

        return displacement

    def get_estimate(self, min_samples: int = 100) -> Optional[HeaveEstimate]:
        """Get heave statistics over the accumulated history.

        Parameters
        ----------
        min_samples : int
            Minimum samples before returning an estimate.

        Returns
        -------
        HeaveEstimate or None if insufficient data.
        """
        if len(self._heave_history) < min_samples:
            return None

        arr = np.array(self._heave_history)
        heave_std = float(np.std(arr))
        heave_max = float(np.max(arr))
        heave_min = float(np.min(arr))
        heave_amplitude = (heave_max - heave_min) / 2.0
        significant_height = 4.0 * heave_std  # standard definition: Hs = 4*sigma

        # Convergence heuristic: need at least accel_bias_window samples
        # and the integral state should be reasonably close to zero
        converged = (
            self._n_processed >= self._accel_bias_window
            and abs(self._x[0]) < 10.0  # integral not diverging
        )

        return HeaveEstimate(
            heave_displacement=float(self._x[1]),
            heave_amplitude=heave_amplitude,
            significant_height=significant_height,
            heave_std=heave_std,
            heave_max=heave_max,
            heave_min=heave_min,
            n_samples=self._n_processed,
            converged=converged,
        )

    @property
    def displacement(self) -> float:
        """Current heave displacement (metres)."""
        return float(self._x[1])

    @property
    def velocity(self) -> float:
        """Current vertical velocity (m/s)."""
        return float(self._x[2])

    @property
    def n_processed(self) -> int:
        return self._n_processed


# --------------------------------------------------------------------------- #
# Butterworth low-pass filter for acceleration pre-processing                  #
# --------------------------------------------------------------------------- #

def butterworth_lowpass(
    data: np.ndarray,
    cutoff_hz: float,
    fs: float,
    order: int = 2,
) -> np.ndarray:
    """Apply a Butterworth low-pass filter to acceleration data.

    Parameters
    ----------
    data : ndarray
        Input acceleration samples.
    cutoff_hz : float
        Cutoff frequency in Hz.
    fs : float
        Sampling frequency in Hz.
    order : int
        Filter order (default 2, as in bareboat-necessities).

    Returns
    -------
    Filtered data array.
    """
    nyq = fs / 2.0
    if cutoff_hz >= nyq:
        return data  # Can't filter above Nyquist
    if len(data) < 3 * order:
        return data  # Too few samples

    sos = scipy_signal.butter(order, cutoff_hz / nyq, btype='low', output='sos')
    return scipy_signal.sosfiltfilt(sos, data)


# --------------------------------------------------------------------------- #
# Hull resonance suppression for PSD peak detection                            #
# --------------------------------------------------------------------------- #

def _hull_resonance_suppression(
    freqs: np.ndarray,
    psd: np.ndarray,
    hull_params: "HullParameters",
    suppression_factor: float = 0.1,
    bandwidth_hz: float = 0.08,
) -> np.ndarray:
    """Suppress hull resonance frequencies in the displacement PSD.

    Applies a notch-like penalty around known hull resonance frequencies
    so that the PSD peak detection prefers ocean swell frequencies over
    hull-amplified response peaks.

    The suppression uses a Gaussian-shaped notch centred on each resonance
    frequency.  At the exact resonance frequency, the PSD is multiplied by
    ``suppression_factor`` (e.g. 0.1 = 90% suppression).  The notch width
    is controlled by ``bandwidth_hz`` (standard deviation of the Gaussian).

    Parameters
    ----------
    freqs : ndarray
        Frequency axis from Welch PSD (Hz).
    psd : ndarray
        Displacement PSD to suppress (modified in-place and returned).
    hull_params : HullParameters
        Known hull resonance parameters.
    suppression_factor : float
        Minimum multiplier at resonance centre (0-1).  Lower = stronger
        suppression.  Default 0.1 (90% suppression).
    bandwidth_hz : float
        Standard deviation of the Gaussian notch in Hz.  Default 0.08 Hz
        covers ±~0.16 Hz (2-sigma) around each resonance.

    Returns
    -------
    Modified PSD array with hull resonance suppressed.
    """
    if bandwidth_hz <= 0:
        return psd

    resonance_freqs: list[float] = []

    # Primary hull resonance (wavelength ~ LOA)
    if hull_params.resonant_period is not None and hull_params.resonant_period > 0:
        resonance_freqs.append(1.0 / hull_params.resonant_period)

    # Beam resonance
    if hull_params.beam_resonant_period is not None and hull_params.beam_resonant_period > 0:
        resonance_freqs.append(1.0 / hull_params.beam_resonant_period)

    # Natural roll/pitch period range — suppress the entire band
    for p_min_attr, p_max_attr in [
        ("natural_roll_period_min", "natural_roll_period_max"),
        ("natural_pitch_period_min", "natural_pitch_period_max"),
    ]:
        p_min = getattr(hull_params, p_min_attr, None)
        p_max = getattr(hull_params, p_max_attr, None)
        if p_min and p_max and p_min > 0 and p_max > 0:
            # Add centre of the natural period band as a resonance
            centre_period = (p_min + p_max) / 2.0
            resonance_freqs.append(1.0 / centre_period)

    if not resonance_freqs:
        return psd

    # De-duplicate close frequencies (within bandwidth_hz)
    unique_freqs: list[float] = []
    for f in sorted(resonance_freqs):
        if not unique_freqs or f - unique_freqs[-1] > bandwidth_hz:
            unique_freqs.append(f)

    # Apply Gaussian notch suppression for each resonance
    result = psd.copy()
    for f_res in unique_freqs:
        # Gaussian: multiplier = 1 - (1 - suppression_factor) * exp(-0.5 * ((f - f_res) / bw)^2)
        gaussian = np.exp(-0.5 * ((freqs - f_res) / bandwidth_hz) ** 2)
        multiplier = 1.0 - (1.0 - suppression_factor) * gaussian
        result *= multiplier

    return result


def _spectral_hs_from_displacement_psd(
    freqs: np.ndarray,
    accel_psd: np.ndarray,
    freq_min_hz: float = 0.03,
    freq_max_hz: float = 1.0,
) -> Optional[float]:
    """Compute Hs from spectral integration of displacement PSD.

    Uses the standard definition: Hs = 4 * sqrt(m0) where m0 is the
    zeroth spectral moment (integral of the displacement PSD).

    This method is independent of peak frequency detection and captures
    ALL wave energy in the band, making it robust to hull resonance
    contamination of the peak frequency.

    Parameters
    ----------
    freqs : ndarray
        Frequency axis (Hz).
    accel_psd : ndarray
        Acceleration PSD (m²/s⁴/Hz).
    freq_min_hz : float
        Lower integration bound.
    freq_max_hz : float
        Upper integration bound.

    Returns
    -------
    Significant wave height in metres, or None if computation fails.
    """
    valid = (freqs > freq_min_hz) & (freqs <= freq_max_hz)
    if not np.any(valid):
        return None

    f_valid = freqs[valid]
    psd_valid = accel_psd[valid]

    # Convert acceleration PSD to displacement PSD:
    #   S_disp(f) = S_accel(f) / (2*pi*f)^4
    omega4 = (2.0 * math.pi * f_valid) ** 4
    omega4[omega4 < 1e-12] = 1e-12
    psd_disp = psd_valid / omega4

    # m0 = integral of displacement PSD over frequency
    if len(f_valid) < 2:
        return None
    _trapz = getattr(np, "trapezoid", getattr(np, "trapz", None))
    if _trapz is None:
        return None
    m0 = float(_trapz(psd_disp, f_valid))
    if m0 <= 0:
        return None

    return 4.0 * math.sqrt(m0)


# --------------------------------------------------------------------------- #
# Combined wave estimator: runs both methods on a window of accel data         #
# --------------------------------------------------------------------------- #

@dataclass
class WaveEstimate:
    """Combined wave height estimate from trochoidal + Kalman methods."""
    # Trochoidal method result (may be None)
    trochoidal: Optional[TrochoidalEstimate] = None
    # Kalman method result (may be None)
    kalman: Optional[HeaveEstimate] = None

    # Best estimate (chosen from available methods)
    significant_height: Optional[float] = None
    heave: Optional[float] = None
    confidence: float = 0.0
    method_used: Optional[str] = None

    # Spectral integration Hs (m0-based, independent of peak freq)
    spectral_hs: Optional[float] = None

    # Accel statistics used
    accel_dominant_freq: Optional[float] = None
    accel_dominant_period: Optional[float] = None
    accel_freq_confidence: Optional[float] = None
    accel_rms: Optional[float] = None
    accel_max: Optional[float] = None


def estimate_waves_from_accel(
    vertical_accel: np.ndarray,
    fs: float,
    delta_v: float = 0.0,
    kalman_estimator: Optional[KalmanHeaveEstimator] = None,
    lowpass_cutoff_mult: float = 8.0,
    psd_min_samples: int = 32,
    freq_min_hz: float = 0.03,
    freq_max_hz: float = 1.0,
    trochoidal_min_amplitude: float = 0.005,
    hull_params: Optional["HullParameters"] = None,
) -> WaveEstimate:
    """Estimate wave height from a window of vertical acceleration data.

    This is the main entry point for wave estimation.  It:
    1. Computes the dominant frequency from PSD of vertical_accel,
       with optional hull-resonance suppression
    2. Computes spectral Hs from displacement PSD integration (m0-based)
    3. Low-pass filters the acceleration
    4. Runs trochoidal estimation from peak accel + frequency
    5. Runs Kalman heave estimation (if estimator provided)
    6. Combines results into a best estimate

    Parameters
    ----------
    vertical_accel : ndarray
        Vertical acceleration samples (m/s^2, gravity removed).
    fs : float
        Sampling rate (Hz).
    delta_v : float
        Boat speed component along wave direction (m/s).
    kalman_estimator : KalmanHeaveEstimator or None
        If provided, each sample is fed to the Kalman filter.
    lowpass_cutoff_mult : float
        Low-pass cutoff = dominant_freq * this multiplier.
    psd_min_samples : int
        Minimum samples for PSD computation.
    freq_min_hz : float
        Lower bound of ocean-wave frequency search band (Hz).
    freq_max_hz : float
        Upper bound of ocean-wave frequency search band (Hz).
        Excludes engine vibration and high-freq noise from PSD peak.
    trochoidal_min_amplitude : float
        Minimum trochoidal wave amplitude (m) to consider real.
    hull_params : HullParameters or None
        If provided, hull resonance frequencies are suppressed in the
        displacement PSD before peak detection.

    Returns
    -------
    WaveEstimate with results from both methods.
    """
    result = WaveEstimate()

    if len(vertical_accel) < psd_min_samples:
        return result

    # --- Acceleration statistics --- #
    result.accel_rms = float(np.sqrt(np.mean(vertical_accel ** 2)))

    # --- Dominant frequency from Welch PSD --- #
    # For ocean waves (0.03–0.5 Hz) at typical IMU rates (50 Hz),
    # we need nperseg >= fs/0.02 ≈ 2500 for adequate resolution.
    # Cap at 2048 as a power-of-two compromise (resolution ≈ 0.024 Hz at 50 Hz).
    nperseg = min(len(vertical_accel) // 2, 2048)
    nperseg = max(nperseg, 8)

    try:
        freqs, psd = scipy_signal.welch(
            vertical_accel - np.mean(vertical_accel),
            fs=fs,
            nperseg=nperseg,
        )
    except Exception:
        return result

    if psd.sum() == 0:
        return result

    # Exclude frequencies outside the ocean-wave band.
    # Lower bound (freq_min_hz) removes DC and infra-gravity noise.
    # Upper bound (freq_max_hz) removes engine vibration / high-freq noise
    # that would otherwise dominate the PSD peak at short wavelengths.
    valid_mask = (freqs > freq_min_hz) & (freqs <= freq_max_hz)
    if not np.any(valid_mask):
        return result

    psd_valid = psd.copy()
    psd_valid[~valid_mask] = 0.0

    if psd_valid.max() == 0:
        return result

    # --- Spectral Hs from m0 integration (independent of peak freq) --- #
    spectral_hs = _spectral_hs_from_displacement_psd(
        freqs, psd_valid, freq_min_hz, freq_max_hz,
    )
    result.spectral_hs = spectral_hs

    # Weight PSD by 1/f² for peak detection.  Ocean wave energy scales
    # roughly as f^{-4} (Pierson–Moskowitz / JONSWAP), but the raw
    # acceleration PSD scales as f^{+2} relative to displacement PSD
    # (acceleration = -ω²·displacement).  Dividing by f² converts the
    # *acceleration* PSD back to a *displacement* PSD, so the peak
    # corresponds to the dominant wave period rather than high-frequency
    # boat vibration or slamming.
    psd_disp = psd_valid.copy()
    freq_sq = freqs ** 2
    freq_sq[freq_sq < 1e-6] = 1e-6  # avoid division by zero at DC
    psd_disp /= freq_sq

    # --- Hull resonance suppression --- #
    # If hull parameters are known, suppress resonance frequencies in the
    # displacement PSD so the peak detector finds ocean swell instead of
    # hull-amplified response.
    if hull_params is not None:
        psd_disp = _hull_resonance_suppression(
            freqs, psd_disp, hull_params,
            suppression_factor=0.1,
            bandwidth_hz=0.08,
        )

    if psd_disp[valid_mask].max() == 0:
        return result

    idx = int(np.argmax(psd_disp))
    dom_freq = float(freqs[idx])

    # Confidence: use the raw (unweighted) PSD peak-to-mean ratio so
    # that the metric still reflects how sharp the spectral peak is.
    peak_power = float(psd_valid[idx])
    mean_power = float(psd_valid[valid_mask].mean()) + 1e-12
    confidence = min(1.0, (peak_power / mean_power) / 10.0)

    result.accel_dominant_freq = dom_freq
    result.accel_dominant_period = 1.0 / dom_freq if dom_freq > 0 else None
    result.accel_freq_confidence = confidence

    logger.debug(
        "PSD peak: freq=%.3f Hz (T=%.1fs), hull_suppression=%s, spectral_hs=%s",
        dom_freq,
        1.0 / dom_freq if dom_freq > 0 else 0,
        "yes" if hull_params is not None else "no",
        f"{spectral_hs:.2f}m" if spectral_hs is not None else "None",
    )

    # --- Low-pass filter --- #
    cutoff = dom_freq * lowpass_cutoff_mult
    filtered = butterworth_lowpass(vertical_accel, cutoff, fs, order=2)

    accel_max = float(np.max(np.abs(filtered)))
    result.accel_max = accel_max

    # --- Trochoidal estimate --- #
    troch = trochoidal_wave_height(
        accel_max, dom_freq, delta_v,
        min_amplitude=trochoidal_min_amplitude,
    )
    if troch is None:
        logger.debug(
            "trochoidal=None: accel_max=%.4f, dom_freq=%.4f, delta_v=%.2f",
            accel_max, dom_freq, delta_v,
        )
    result.trochoidal = troch

    # --- Kalman heave --- #
    if kalman_estimator is not None:
        for sample in filtered:
            kalman_estimator.update(float(sample))
        kalman_est = kalman_estimator.get_estimate()
        result.kalman = kalman_est

    # --- Best estimate selection --- #
    # Priority: spectral Hs as sanity check, then Kalman > trochoidal.
    # If spectral_hs is available and significantly larger than trochoidal,
    # prefer spectral (it captures all energy, not just the peak).
    if troch is not None and result.kalman is not None and result.kalman.converged:
        hs_kalman = result.kalman.significant_height
        hs_troch = troch.significant_height
        ratio = hs_kalman / (hs_troch + 1e-6)

        if 0.3 < ratio < 3.0:
            result.significant_height = hs_kalman
            result.heave = result.kalman.heave_displacement
            result.method_used = "kalman"
            result.confidence = min(confidence, 0.8 if result.kalman.converged else 0.4)
        else:
            result.significant_height = hs_troch
            result.heave = result.kalman.heave_displacement
            result.method_used = "trochoidal"
            result.confidence = confidence * 0.5
    elif troch is not None:
        result.significant_height = troch.significant_height
        result.method_used = "trochoidal"
        result.confidence = confidence * 0.6
    elif result.kalman is not None and result.kalman.converged:
        result.significant_height = result.kalman.significant_height
        result.heave = result.kalman.heave_displacement
        result.method_used = "kalman"
        result.confidence = 0.4 if result.kalman.converged else 0.2

    # --- Spectral cross-check --- #
    # If spectral Hs is available and the chosen estimate is significantly
    # lower (< 40% of spectral), upgrade to spectral.  This catches cases
    # where hull resonance or poor peak detection underestimates Hs.
    if spectral_hs is not None and spectral_hs > 0.05:
        if result.significant_height is None:
            result.significant_height = spectral_hs
            result.method_used = "spectral"
            result.confidence = confidence * 0.5
        elif result.significant_height < spectral_hs * 0.4:
            logger.debug(
                "spectral cross-check: upgrading Hs from %.2f to %.2f (spectral)",
                result.significant_height, spectral_hs,
            )
            result.significant_height = spectral_hs
            result.method_used = "spectral"
            result.confidence = confidence * 0.5

    return result
