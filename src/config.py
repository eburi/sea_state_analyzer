"""Configuration for the Signal K wave-learner prototype.

All tunable parameters live here.  Module-level DEFAULT_CONFIG is used by
callers that do not supply an explicit Config instance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple
import logging


@dataclass
class Config:
    # ------------------------------------------------------------------ #
    # Signal K connection                                                  #
    # ------------------------------------------------------------------ #
    base_url: str = "http://homeassistant.local:3000"
    ws_url: str = "ws://homeassistant.local:3000/signalk/v1/stream?subscribe=none"
    vessel_self_context: str = "vessels.self"

    # Reconnect back-off delays in seconds
    reconnect_delays: List[float] = field(
        default_factory=lambda: [1.0, 2.0, 5.0, 10.0, 30.0]
    )

    # ------------------------------------------------------------------ #
    # Sampling                                                             #
    # ------------------------------------------------------------------ #
    sample_rate_hz: float = 2.0  # canonical InstantSample rate

    # ------------------------------------------------------------------ #
    # Rolling windows                                                      #
    # ------------------------------------------------------------------ #
    rolling_windows_s: List[int] = field(default_factory=lambda: [10, 30, 60, 300])

    # ------------------------------------------------------------------ #
    # Data freshness                                                       #
    # ------------------------------------------------------------------ #
    # Fields older than this are flagged invalid (seconds)
    stale_threshold_s: float = 10.0

    # ------------------------------------------------------------------ #
    # Output                                                               #
    # ------------------------------------------------------------------ #
    output_base_dir: Path = field(
        default_factory=lambda: Path.home() / ".sea_state_analyzer" / "output"
    )

    # ------------------------------------------------------------------ #
    # Logging                                                               #
    # ------------------------------------------------------------------ #
    log_level: int = logging.INFO

    # ------------------------------------------------------------------ #
    # Plots                                                                #
    # ------------------------------------------------------------------ #
    enable_live_plots: bool = False
    plot_interval_s: float = 30.0

    # ------------------------------------------------------------------ #
    # Console summary                                                      #
    # ------------------------------------------------------------------ #
    console_interval_s: float = 5.0

    # ------------------------------------------------------------------ #
    # Spectral analysis                                                    #
    # ------------------------------------------------------------------ #
    # Frequency bands (Hz) used for spectral-energy features
    freq_bands: List[Tuple[float, float]] = field(
        default_factory=lambda: [
            (0.05, 0.10),
            (0.10, 0.20),
            (0.20, 0.40),
            (0.40, 1.00),
        ]
    )
    # Minimum samples to attempt PSD analysis
    psd_min_samples: int = 16

    # ------------------------------------------------------------------ #
    # Motion severity heuristic                                            #
    # ------------------------------------------------------------------ #
    severity_roll_rms_max: float = 0.35  # rad  (~20 deg)
    severity_pitch_rms_max: float = 0.175  # rad  (~10 deg)
    severity_roll_spectral_max: float = 0.10
    severity_yaw_rate_var_max: float = 0.01

    severity_weights: Dict[str, float] = field(
        default_factory=lambda: {
            "roll_rms": 0.35,
            "pitch_rms": 0.25,
            "roll_spectral": 0.25,
            "yaw_rate_var": 0.15,
        }
    )
    # Exponential smoothing alpha for severity (0 = no update, 1 = no memory)
    severity_smoothing_alpha: float = 0.1

    # ------------------------------------------------------------------ #
    # Doppler correction                                                   #
    # ------------------------------------------------------------------ #
    # Rudder angle std threshold (rad) – above this the boat is manoeuvring
    # and Doppler correction is unreliable
    doppler_rudder_std_max: float = 0.10  # ~5.7 deg

    # Minimum depth (m) for deep-water assumption.  Deep-water requires
    # depth > wavelength/2.  This is a conservative floor: if mean depth is
    # below this, we flag Doppler results but still compute them.
    doppler_shallow_depth_m: float = 10.0

    # Minimum STW (m/s) required to attempt Doppler correction
    doppler_min_stw: float = 0.5  # ~1 knot

    # ------------------------------------------------------------------ #
    # IMU                                                                  #
    # ------------------------------------------------------------------ #
    imu_enabled: bool = True  # attempt IMU init; False disables
    imu_bus_number: int = 1  # i2c bus (RPi default = 1)
    imu_auto_detect: bool = True  # scan I2C for known IMU chips
    imu_address: int = 0x68  # fallback address if auto-detect off/fails
    imu_sample_rate_hz: float = 50.0  # target IMU poll rate
    imu_include_mag: bool = True  # include magnetometer (slower)

    # ------------------------------------------------------------------ #
    # Signal K publishing                                                  #
    # ------------------------------------------------------------------ #
    publish_to_signalk: bool = True  # send wave estimates back to SK
    publish_interval_s: float = 5.0  # seconds between publishes
    publish_source_label: str = "sea_state_analyzer"

    # ------------------------------------------------------------------ #
    # Signal K authentication                                              #
    # ------------------------------------------------------------------ #
    # Path to persist the device clientId and JWT token across restarts.
    # Default uses ~/.sea_state_analyzer/ so it works on bare Raspbian;
    # HA run.sh overrides to /data/signalk_token.json.
    auth_token_file: str = field(
        default_factory=lambda: str(
            Path.home() / ".sea_state_analyzer" / "signalk_token.json"
        )
    )
    # Description shown in Signal K admin UI when requesting device access.
    auth_device_description: str = "Sea State Analyzer"
    # How long to poll for user approval before giving up (seconds).
    auth_approval_timeout_s: float = 300.0
    # Interval between polling requests while waiting for approval.
    auth_poll_interval_s: float = 5.0

    # ------------------------------------------------------------------ #
    # Online learning (Phase 3)                                            #
    # ------------------------------------------------------------------ #
    # Path to persist the learned vessel RAO model.
    # Default uses ~/.sea_state_analyzer/ so it works on bare Raspbian;
    # HA run.sh overrides to /data/vessel_rao.json.
    learner_persist_path: str = field(
        default_factory=lambda: str(
            Path.home() / ".sea_state_analyzer" / "vessel_rao.json"
        )
    )

    # ------------------------------------------------------------------ #
    # Heave / wave height estimation                                       #
    # ------------------------------------------------------------------ #
    # Kalman filter tuning (Sharkh et al. 2014)
    heave_kalman_pos_integral_trans_var: float = 1e-6
    heave_kalman_pos_trans_var: float = 1e-4
    heave_kalman_vel_trans_var: float = 1e-2
    heave_kalman_pos_integral_obs_var: float = 1e1
    heave_kalman_bias_window: int = (
        5000  # samples (~100s at 50Hz) for accel bias estimate
    )

    # Low-pass filter: cutoff = dominant_freq * multiplier
    heave_lowpass_cutoff_mult: float = 8.0

    # PSD frequency search band for ocean waves (Hz).
    # Upper bound excludes engine vibration / high-freq noise from PSD peak.
    heave_freq_min_hz: float = 0.03  # ~33 s period (long swell)
    heave_freq_max_hz: float = 1.0  # ~1 s period (steep wind chop)

    # Minimum amplitude (m) for trochoidal wave to be considered real.
    # 0.005 m = 5 mm — below this the model's precision is unreliable.
    heave_trochoidal_min_amplitude: float = 0.005

    # Minimum samples of vertical_accel in a window to attempt wave estimation
    heave_min_accel_samples: int = 32

    # ------------------------------------------------------------------ #
    # Derivative computation                                               #
    # ------------------------------------------------------------------ #
    # Trailing moving-average window applied to raw finite-difference
    derivative_filter_window: int = 5

    # ------------------------------------------------------------------ #
    # Recorder                                                             #
    # ------------------------------------------------------------------ #
    parquet_batch_size: int = 200  # rows before flushing to Parquet

    # ------------------------------------------------------------------ #
    # Async queues                                                          #
    # ------------------------------------------------------------------ #
    delta_queue_maxsize: int = 1000
    sample_queue_maxsize: int = 500

    # ------------------------------------------------------------------ #
    # Inspect mode                                                          #
    # ------------------------------------------------------------------ #
    inspect_duration_s: float = 60.0  # how long to observe before reporting

    # ------------------------------------------------------------------ #
    # Replay                                                                #
    # ------------------------------------------------------------------ #
    replay_speed: float = 0.0  # 0 = as-fast-as-possible; >0 = real-time multiplier

    # ------------------------------------------------------------------ #
    # Helpers                                                               #
    # ------------------------------------------------------------------ #
    def dated_output_dir(self) -> Path:
        """Create and return a session-stamped sub-directory under output_base_dir."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        p = self.output_base_dir / ts
        p.mkdir(parents=True, exist_ok=True)
        return p

    @classmethod
    def from_env(cls) -> "Config":
        """Create a Config with overrides from SEA_STATE_* environment variables.

        Used by the HA App entry point (run.sh) to pass options.json values
        into the Python process.  Any env var that is not set falls back to
        the dataclass default.
        """
        import os

        def _env(key: str) -> str | None:
            return os.environ.get(f"SEA_STATE_{key}")

        def _env_bool(key: str) -> bool | None:
            v = _env(key)
            if v is None:
                return None
            return v.lower() in ("true", "1", "yes")

        def _env_float(key: str) -> float | None:
            v = _env(key)
            if v is None:
                return None
            try:
                return float(v)
            except ValueError:
                return None

        def _env_int(key: str) -> int | None:
            v = _env(key)
            if v is None:
                return None
            try:
                return int(v)
            except ValueError:
                return None

        kwargs: dict = {}

        url = _env("SIGNALK_URL")
        if url:
            kwargs["base_url"] = url
            kwargs["ws_url"] = (
                url.replace("http://", "ws://").replace("https://", "wss://")
                + "/signalk/v1/stream?subscribe=none"
            )

        sr = _env_float("SAMPLE_RATE_HZ")
        if sr is not None:
            kwargs["sample_rate_hz"] = sr

        ie = _env_bool("IMU_ENABLED")
        if ie is not None:
            kwargs["imu_enabled"] = ie

        ib = _env_int("IMU_BUS_NUMBER")
        if ib is not None:
            kwargs["imu_bus_number"] = ib

        iad = _env_bool("IMU_AUTO_DETECT")
        if iad is not None:
            kwargs["imu_auto_detect"] = iad

        ia = _env_int("IMU_ADDRESS")
        if ia is not None:
            kwargs["imu_address"] = ia

        isr = _env_float("IMU_SAMPLE_RATE_HZ")
        if isr is not None:
            kwargs["imu_sample_rate_hz"] = isr

        im = _env_bool("IMU_INCLUDE_MAG")
        if im is not None:
            kwargs["imu_include_mag"] = im

        ps = _env_bool("PUBLISH_TO_SIGNALK")
        if ps is not None:
            kwargs["publish_to_signalk"] = ps

        atf = _env("AUTH_TOKEN_FILE")
        if atf:
            kwargs["auth_token_file"] = atf

        lpp = _env("LEARNER_PERSIST_PATH")
        if lpp:
            kwargs["learner_persist_path"] = lpp

        ep = _env_bool("ENABLE_PLOTS")
        if ep is not None:
            kwargs["enable_live_plots"] = ep

        ll = _env("LOG_LEVEL")
        if ll is not None:
            level_map = {
                "debug": logging.DEBUG,
                "info": logging.INFO,
                "warning": logging.WARNING,
                "error": logging.ERROR,
            }
            kwargs["log_level"] = level_map.get(ll.lower(), logging.INFO)

        od = _env("OUTPUT_DIR")
        if od:
            kwargs["output_base_dir"] = Path(od)

        return cls(**kwargs)


# Module-level default used throughout the project
DEFAULT_CONFIG = Config()
