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
    base_url: str = "http://primrose.local:3000"
    ws_url: str = "ws://primrose.local:3000/signalk/v1/stream?subscribe=none"
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
    rolling_windows_s: List[int] = field(
        default_factory=lambda: [10, 30, 60, 300]
    )

    # ------------------------------------------------------------------ #
    # Data freshness                                                       #
    # ------------------------------------------------------------------ #
    # Fields older than this are flagged invalid (seconds)
    stale_threshold_s: float = 10.0

    # ------------------------------------------------------------------ #
    # Output                                                               #
    # ------------------------------------------------------------------ #
    output_base_dir: Path = field(default_factory=lambda: Path("output"))

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
    severity_roll_rms_max: float = 0.35    # rad  (~20 deg)
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
    doppler_rudder_std_max: float = 0.10   # ~5.7 deg

    # Minimum depth (m) for deep-water assumption.  Deep-water requires
    # depth > wavelength/2.  This is a conservative floor: if mean depth is
    # below this, we flag Doppler results but still compute them.
    doppler_shallow_depth_m: float = 10.0

    # Minimum STW (m/s) required to attempt Doppler correction
    doppler_min_stw: float = 0.5  # ~1 knot

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


# Module-level default used throughout the project
DEFAULT_CONFIG = Config()
