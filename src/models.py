"""Typed data structures used throughout the wave-learner pipeline.

All angles are in radians, speeds in m/s, time as timezone-aware UTC datetimes
unless explicitly noted otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------- #
# Raw ingest                                                                   #
# --------------------------------------------------------------------------- #


@dataclass
class RawDeltaMessage:
    """A Signal K delta exactly as received from the WebSocket."""

    received_at: datetime  # wall-clock UTC time of receipt
    context: str  # e.g. "vessels.self" or full URN
    updates: List[Dict[str, Any]]  # the raw 'updates' array
    raw: Dict[str, Any]  # full unparsed message dict


@dataclass
class SignalKValueUpdate:
    """A single path/value pair extracted from a delta update."""

    path: str
    value: Any
    source: Optional[str]
    timestamp: Optional[datetime]  # source timestamp if present
    received_at: datetime  # wall-clock receipt time


# --------------------------------------------------------------------------- #
# State store internals                                                        #
# --------------------------------------------------------------------------- #


@dataclass
class FieldState:
    """Current known state of a single Signal K path."""

    value: Any
    source: Optional[str]
    source_timestamp: Optional[datetime]
    received_at: datetime

    def age_s(self, now: datetime) -> float:
        return (now - self.received_at).total_seconds()


# --------------------------------------------------------------------------- #
# Canonical vessel self snapshot                                               #
# --------------------------------------------------------------------------- #


@dataclass
class InstantSample:
    """
    Merged vessel self-state snapshot at a single timestamp.

    All angles in radians, speeds in m/s.  Fields that are unknown or stale
    are None.  field_ages gives the data age in seconds for each field;
    field_valid gives the freshness boolean (age < stale_threshold).
    """

    timestamp: datetime

    # Attitude (rad)
    roll: Optional[float] = None
    pitch: Optional[float] = None
    yaw: Optional[float] = None

    # Movement
    sog: Optional[float] = None  # m/s
    cog: Optional[float] = None  # rad
    heading: Optional[float] = None  # rad

    # Speed through water
    stw: Optional[float] = None  # m/s (paddle wheel / log)

    # Wind
    wind_speed_true: Optional[float] = None  # m/s
    wind_angle_true: Optional[float] = None  # rad, relative to bow
    wind_direction_true: Optional[float] = None  # rad, relative to true north
    wind_speed_apparent: Optional[float] = None  # m/s
    wind_angle_apparent: Optional[float] = None  # rad, relative to bow

    # Current
    current_drift: Optional[float] = None  # m/s
    current_set: Optional[float] = None  # rad (direction current flows toward)

    # Steering
    rudder_angle: Optional[float] = None  # rad
    autopilot_state: Optional[str] = None  # wind / route / standby

    # Depth
    depth: Optional[float] = None  # metres below transducer

    # IMU accelerometer (m/s²) — raw, in sensor frame
    accel_x: Optional[float] = None
    accel_y: Optional[float] = None
    accel_z: Optional[float] = None

    # IMU gyroscope (rad/s) — raw, in sensor frame
    gyro_x: Optional[float] = None
    gyro_y: Optional[float] = None
    gyro_z: Optional[float] = None

    # IMU magnetometer (µT)
    mag_x: Optional[float] = None
    mag_y: Optional[float] = None
    mag_z: Optional[float] = None

    # Vertical acceleration (m/s², z minus gravity)
    vertical_accel: Optional[float] = None

    # Rate of turn
    rate_of_turn: Optional[float] = None  # rad/s

    # Position (degrees)
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Freshness metadata
    field_ages: Dict[str, float] = field(default_factory=dict)  # seconds
    field_valid: Dict[str, bool] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Layer A: instantaneous derived values                                        #
# --------------------------------------------------------------------------- #


@dataclass
class LayerAFeatures:
    """Instantaneous derived motion metrics computed from consecutive samples."""

    timestamp: datetime

    roll_rate: Optional[float] = None  # rad/s
    pitch_rate: Optional[float] = None  # rad/s
    yaw_rate_derived: Optional[float] = None  # rad/s (from attitude, not RoT sensor)

    roll_acceleration: Optional[float] = None  # rad/s²
    pitch_acceleration: Optional[float] = None
    yaw_acceleration: Optional[float] = None

    heading_minus_cog: Optional[float] = None  # rad, leeway proxy
    wind_angle_true_bow: Optional[float] = None  # rad, true wind angle relative to bow
    wind_angle_apparent_bow: Optional[float] = None

    roll_normalized: Optional[float] = (
        None  # roll / speed  (STW preferred, SOG fallback)
    )
    pitch_normalized: Optional[float] = None  # pitch / speed


# --------------------------------------------------------------------------- #
# Layer B+C: rolling window features and motion proxies                       #
# --------------------------------------------------------------------------- #


@dataclass
class WindowFeatures:
    """Rolling-window motion statistics for a single window duration."""

    timestamp: datetime
    window_s: float
    n_samples: int

    # Roll statistics
    roll_mean: Optional[float] = None
    roll_std: Optional[float] = None
    roll_rms: Optional[float] = None
    roll_p2p: Optional[float] = None
    roll_kurtosis: Optional[float] = None
    roll_crest_factor: Optional[float] = None
    roll_zero_crossing_period: Optional[float] = None
    roll_dominant_freq: Optional[float] = None
    roll_dominant_period: Optional[float] = None
    roll_period_confidence: Optional[float] = None
    roll_spectral_energy: Optional[float] = None

    # Pitch statistics
    pitch_mean: Optional[float] = None
    pitch_std: Optional[float] = None
    pitch_rms: Optional[float] = None
    pitch_p2p: Optional[float] = None
    pitch_kurtosis: Optional[float] = None
    pitch_crest_factor: Optional[float] = None
    pitch_zero_crossing_period: Optional[float] = None
    pitch_dominant_freq: Optional[float] = None
    pitch_dominant_period: Optional[float] = None
    pitch_period_confidence: Optional[float] = None
    pitch_spectral_energy: Optional[float] = None

    # Cross-signal variance metrics
    yaw_rate_var: Optional[float] = None
    sog_var: Optional[float] = None
    stw_var: Optional[float] = None
    heading_cog_var: Optional[float] = None
    wind_speed_var: Optional[float] = None
    wind_angle_var: Optional[float] = None
    wind_angle_mean: Optional[float] = (
        None  # rad, circular mean of true wind angle relative to bow
    )

    # Spectral entropy (over roll+pitch combined)
    spectral_entropy_roll: Optional[float] = None
    spectral_entropy_pitch: Optional[float] = None

    # Spectral energy by band {band_label: energy}
    spectral_bands_roll: Optional[Dict[str, float]] = None
    spectral_bands_pitch: Optional[Dict[str, float]] = None

    # Period stability (std of dominant period across last N sub-windows)
    roll_period_stability: Optional[float] = None
    pitch_period_stability: Optional[float] = None

    # STW statistics (for Doppler correction quality)
    stw_mean: Optional[float] = None
    stw_std: Optional[float] = None

    # Rudder angle statistics (for manoeuvre detection)
    rudder_angle_mean: Optional[float] = None
    rudder_angle_std: Optional[float] = None

    # Depth statistics (for deep-water validation)
    depth_mean: Optional[float] = None

    # Current drift (from environment.current.drift; 0 when unavailable)
    current_drift_mean: Optional[float] = None  # m/s


@dataclass
class MotionEstimate:
    """
    Inferred wave-motion proxies derived from vessel self motion only.

    IMPORTANT: These are motion-based inferences about vessel response to
    sea state.  They are NOT direct measurements of wave height, direction,
    or wavelength.  Sail trim, point of sail, hull form, autopilot, loading,
    and displacement all modulate these values.
    """

    timestamp: datetime
    window_s: float

    # Vessel position at estimate time
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Motion severity 0–1 (instantaneous heuristic score)
    motion_severity: Optional[float] = None
    motion_severity_smoothed: Optional[float] = None

    # Regime label: calm / moderate / active / heavy
    motion_regime: Optional[str] = None

    # Inferred encounter period (seconds)
    dominant_roll_period: Optional[float] = None
    dominant_pitch_period: Optional[float] = None
    encounter_period_estimate: Optional[float] = None
    period_confidence: Optional[float] = None

    # Doppler-corrected true wave estimates
    true_wave_period: Optional[float] = None  # seconds (source wave period)
    true_wavelength: Optional[float] = None  # metres
    wave_speed: Optional[float] = None  # m/s (phase velocity)
    doppler_delta_v: Optional[float] = None  # m/s (STW * cos(TWA))
    doppler_correction_valid: Optional[bool] = None  # whether correction was feasible
    wave_heading: Optional[str] = None  # head / following / beam / quartering

    # Encounter direction proxy
    # With wind angle: head_like / head_quartering_like / beam_like /
    #   following_quartering_like / following_like / confused_like
    # Without wind angle (fallback): head_or_following_like /
    #   beam_like / quartering_like / confused_like / mixed
    encounter_direction: Optional[str] = None
    direction_confidence: Optional[float] = None

    # Motion character
    roll_dominant: Optional[bool] = None  # roll > pitch energy
    motion_regularity: Optional[str] = None  # regular / confused / mixed
    confusion_index: Optional[float] = None  # 0=regular, 1=confused

    # Comfort proxy (0=very uncomfortable, 1=comfortable)
    comfort_proxy: Optional[float] = None

    # Wave height estimation (from IMU accelerometer)
    significant_height: Optional[float] = None  # metres (Hs)
    heave: Optional[float] = None  # metres (current heave displacement)
    wave_height_method: Optional[str] = None  # "trochoidal" / "kalman"
    wave_height_confidence: Optional[float] = None  # 0–1

    # Accelerometer-derived wave frequency (independent of attitude PSD)
    accel_dominant_freq: Optional[float] = None  # Hz
    accel_dominant_period: Optional[float] = None  # seconds
    accel_freq_confidence: Optional[float] = None  # 0–1

    # Partitioned wave components from multi-peak spectral analysis
    wind_wave_height: Optional[float] = None
    wind_wave_period: Optional[float] = None
    wind_wave_freq: Optional[float] = None
    wind_wave_confidence: Optional[float] = None

    swell_1_height: Optional[float] = None
    swell_1_period: Optional[float] = None
    swell_1_freq: Optional[float] = None
    swell_1_confidence: Optional[float] = None

    swell_2_height: Optional[float] = None
    swell_2_period: Optional[float] = None
    swell_2_freq: Optional[float] = None
    swell_2_confidence: Optional[float] = None

    # Trend compared to a longer window: improving / worsening / stable
    severity_trend: Optional[str] = None

    # RAO correction applied (hull amplification factor at observed period)
    rao_gain_applied: Optional[float] = None

    # Douglas sea-state scale (WMO Code 3700) — from Hs
    douglas_sea_state: Optional[int] = None  # degree 0-9
    douglas_sea_state_label: Optional[str] = None  # e.g. "Moderate"

    # Douglas swell scale (WMO Code 3701) — from swell Hs + wavelength
    douglas_swell: Optional[int] = None  # degree 0-9
    douglas_swell_label: Optional[str] = None

    # Beaufort wind force — from true wind speed
    beaufort_force: Optional[int] = None  # force 0-12
    beaufort_label: Optional[str] = None  # e.g. "Strong breeze"

    # Overall confidence in the estimates
    overall_confidence: Optional[float] = None


# --------------------------------------------------------------------------- #
# System status                                                                #
# --------------------------------------------------------------------------- #


@dataclass
class SystemStatus:
    """Operational state of the pipeline."""

    timestamp: datetime
    connected: bool
    ws_url: str
    samples_produced: int
    sample_rate_hz: float
    fields_fresh: Dict[str, bool]
    uptime_s: float
    last_delta_at: Optional[datetime] = None
    reconnect_count: int = 0
    error_count: int = 0
