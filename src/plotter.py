"""Plotter module: live terminal summaries and optional matplotlib plots.

Terminal summaries are printed to stdout at a configurable interval and are
always active.  Matplotlib plots are generated only when
config.enable_live_plots is True and are written to the output directory as
PNG files (no GUI required by default).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from config import Config, DEFAULT_CONFIG
from models import InstantSample, MotionEstimate, SystemStatus, WindowFeatures

logger = logging.getLogger(__name__)

# Lazy import matplotlib only when plots are needed
_mpl_available = False
try:
    import matplotlib

    matplotlib.use("Agg")  # non-interactive backend; no display required
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    _mpl_available = True
except ImportError:
    pass


def _rad_to_deg(v: Optional[float]) -> Optional[float]:
    return math.degrees(v) if v is not None else None


def _ms_to_knots(v: Optional[float]) -> Optional[float]:
    return v * 1.94384 if v is not None else None


def _fmt(v: Optional[float], fmt: str = ".2f", unit: str = "") -> str:
    if v is None:
        return "  --  "
    return f"{v:{fmt}}{unit}"


def _bar(value: float, width: int = 20) -> str:
    """ASCII progress bar for a 0–1 value."""
    filled = round(max(0.0, min(1.0, value)) * width)
    return "[" + "█" * filled + "░" * (width - filled) + "]"


# --------------------------------------------------------------------------- #
# Console summary                                                              #
# --------------------------------------------------------------------------- #


class TerminalPlotter:
    """
    Prints a machine-readable live summary to stdout every console_interval_s.
    Output uses key=value format suitable for log parsing and `ha apps logs`.
    Does not block the asyncio event loop -- call print_summary() from a task.
    """

    def __init__(self, config: Config = DEFAULT_CONFIG) -> None:
        self._config = config
        self._line_count = 0

    def print_summary(
        self,
        status: SystemStatus,
        sample: Optional[InstantSample],
        wf_short: Optional[WindowFeatures],
        me: Optional[MotionEstimate],
    ) -> None:
        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        conn_str = "up" if status.connected else "down"

        lines = [
            f"--- sea_state {now_str}Z conn={conn_str} "
            f"samples={status.samples_produced} rate={status.sample_rate_hz:.1f}Hz "
            f"reconnects={status.reconnect_count}",
        ]

        if sample is not None:
            roll_deg = _rad_to_deg(sample.roll)
            pitch_deg = _rad_to_deg(sample.pitch)
            heading_deg = _rad_to_deg(sample.heading)
            cog_deg = _rad_to_deg(sample.cog)
            lines.append(
                f"  att: roll={_fmt(roll_deg, '.1f', 'deg')} "
                f"pitch={_fmt(pitch_deg, '.1f', 'deg')} "
                f"hdg={_fmt(heading_deg, '.1f', 'deg')} "
                f"cog={_fmt(cog_deg, '.1f', 'deg')} "
                f"sog={_fmt(sample.sog, '.2f', 'm/s')}"
            )
            if sample.wind_speed_true is not None:
                tws_kn = _ms_to_knots(sample.wind_speed_true)
                twa_deg = _rad_to_deg(sample.wind_angle_true)
                aws_kn = _ms_to_knots(sample.wind_speed_apparent)
                awa_deg = _rad_to_deg(sample.wind_angle_apparent)
                lines.append(
                    f"  wind: tws={_fmt(tws_kn, '.1f', 'kn')} "
                    f"twa={_fmt(twa_deg, '.0f', 'deg')} "
                    f"aws={_fmt(aws_kn, '.1f', 'kn')} "
                    f"awa={_fmt(awa_deg, '.0f', 'deg')}"
                )

        if wf_short is not None:
            roll_rms_deg = _rad_to_deg(wf_short.roll_rms)
            pitch_rms_deg = _rad_to_deg(wf_short.pitch_rms)
            lines.append(
                f"  motion({int(wf_short.window_s)}s): "
                f"roll_rms={_fmt(roll_rms_deg, '.1f', 'deg')} "
                f"pitch_rms={_fmt(pitch_rms_deg, '.1f', 'deg')} "
                f"roll_T={_fmt(wf_short.roll_dominant_period, '.1f', 's')} "
                f"pitch_T={_fmt(wf_short.pitch_dominant_period, '.1f', 's')}"
            )

        if me is not None:
            sev = me.motion_severity_smoothed or 0.0
            lines.append(
                f"  severity={sev:.3f} "
                f"regime={me.motion_regime or '--'} "
                f"trend={me.severity_trend or '--'} "
                f"direction={me.encounter_direction or '--'} "
                f"dir_conf={_fmt(me.direction_confidence, '.2f')}"
            )
            lines.append(
                f"  regularity={me.motion_regularity or '--'} "
                f"confusion={_fmt(me.confusion_index, '.2f')} "
                f"comfort={_fmt(me.comfort_proxy, '.3f')} "
                f"overall_conf={_fmt(me.overall_confidence, '.2f')}"
            )
            if me.significant_height is not None:
                lines.append(
                    f"  waves: Hs={_fmt(me.significant_height, '.2f', 'm')} "
                    f"heave={_fmt(me.heave, '.3f', 'm')} "
                    f"method={me.wave_height_method or '--'} "
                    f"conf={_fmt(me.wave_height_confidence, '.2f')}"
                )
            if me.accel_dominant_period is not None:
                lines.append(
                    f"  accel: T={_fmt(me.accel_dominant_period, '.1f', 's')} "
                    f"freq={_fmt(me.accel_dominant_freq, '.3f', 'Hz')} "
                    f"rao={_fmt(me.rao_gain_applied, '.3f')}"
                )
            # Scale classifications
            scale_parts = []
            if me.douglas_sea_state is not None:
                scale_parts.append(
                    f"Douglas={me.douglas_sea_state}({me.douglas_sea_state_label})"
                )
            if me.douglas_swell is not None:
                scale_parts.append(
                    f"Swell={me.douglas_swell}({me.douglas_swell_label})"
                )
            if me.beaufort_force is not None:
                scale_parts.append(f"Bft={me.beaufort_force}({me.beaufort_label})")
            if scale_parts:
                lines.append(f"  scales: {' '.join(scale_parts)}")

        # Stale field warnings
        if sample is not None and sample.field_valid:
            stale = [k for k, v in sample.field_valid.items() if not v]
            if stale:
                lines.append(f"  stale: {', '.join(stale)}")

        print("\n".join(lines))


# --------------------------------------------------------------------------- #
# Matplotlib plots                                                             #
# --------------------------------------------------------------------------- #


class FilePlotter:
    """
    Periodically generates PNG plot files from buffered samples.
    Only used when config.enable_live_plots = True and matplotlib is available.
    """

    MAX_POINTS = 600  # max samples per plot to avoid huge files

    def __init__(self, output_dir: Path, config: Config = DEFAULT_CONFIG) -> None:
        self._dir = output_dir
        self._config = config

    def plot_all(
        self,
        samples: List[InstantSample],
        window_features: Dict[int, List[WindowFeatures]],
        motion_estimates: List[MotionEstimate],
    ) -> None:
        if not _mpl_available:
            logger.warning("matplotlib not available; skipping plots")
            return
        if not samples:
            return

        try:
            self._plot_attitude(samples)
            self._plot_heading_cog(samples)
            self._plot_psd(samples)
            if motion_estimates:
                self._plot_severity(motion_estimates)
                self._plot_period(motion_estimates)
            if samples:
                self._plot_roll_vs_wind(samples)
                self._plot_pitch_vs_sog(samples)
        except Exception as exc:
            logger.warning("Plot generation failed: %s", exc)

    def _decimate(self, lst: list) -> list:
        if len(lst) <= self.MAX_POINTS:
            return lst
        step = len(lst) // self.MAX_POINTS
        return lst[::step]

    def _plot_attitude(self, samples: List[InstantSample]) -> None:
        s = self._decimate(samples)
        times = [x.timestamp for x in s]
        rolls = [
            math.degrees(x.roll) if x.roll is not None else float("nan") for x in s
        ]
        pitches = [
            math.degrees(x.pitch) if x.pitch is not None else float("nan") for x in s
        ]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 5), sharex=True)
        ax1.plot(times, rolls, lw=0.8, color="steelblue")
        ax1.set_ylabel("Roll (deg)")
        ax1.axhline(0, color="gray", lw=0.5, ls="--")
        ax2.plot(times, pitches, lw=0.8, color="coral")
        ax2.set_ylabel("Pitch (deg)")
        ax2.axhline(0, color="gray", lw=0.5, ls="--")
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        plt.suptitle("Roll / Pitch time series")
        plt.tight_layout()
        fig.savefig(self._dir / "plot_attitude.png", dpi=100)
        plt.close(fig)

    def _plot_heading_cog(self, samples: List[InstantSample]) -> None:
        s = self._decimate(samples)
        times = [x.timestamp for x in s]
        headings = [
            math.degrees(x.heading) if x.heading is not None else float("nan")
            for x in s
        ]
        cogs = [math.degrees(x.cog) if x.cog is not None else float("nan") for x in s]

        fig, ax = plt.subplots(figsize=(12, 3))
        ax.plot(times, headings, lw=0.8, label="Heading", color="steelblue")
        ax.plot(times, cogs, lw=0.8, label="COG", color="orange", ls="--")
        ax.set_ylabel("Degrees")
        ax.legend()
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        plt.suptitle("Heading vs COG")
        plt.tight_layout()
        fig.savefig(self._dir / "plot_heading_cog.png", dpi=100)
        plt.close(fig)

    def _plot_psd(self, samples: List[InstantSample]) -> None:
        import numpy as np
        from scipy import signal as sp_signal

        rolls = [x.roll for x in samples if x.roll is not None]
        pitches = [x.pitch for x in samples if x.pitch is not None]
        if len(rolls) < 16 or len(pitches) < 16:
            return

        fs = self._config.sample_rate_hz
        nperseg = min(256, len(rolls) // 2)

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
        f_r, p_r = sp_signal.welch(
            np.array(rolls) - np.mean(rolls), fs=fs, nperseg=nperseg
        )
        ax1.semilogy(f_r, p_r, color="steelblue")
        ax1.set_xlabel("Frequency (Hz)")
        ax1.set_ylabel("PSD")
        ax1.set_title("Roll PSD")

        f_p, p_p = sp_signal.welch(
            np.array(pitches) - np.mean(pitches), fs=fs, nperseg=nperseg
        )
        ax2.semilogy(f_p, p_p, color="coral")
        ax2.set_xlabel("Frequency (Hz)")
        ax2.set_title("Pitch PSD")

        plt.tight_layout()
        fig.savefig(self._dir / "plot_psd.png", dpi=100)
        plt.close(fig)

    def _plot_severity(self, estimates: List[MotionEstimate]) -> None:
        e = self._decimate(estimates)
        times = [x.timestamp for x in e]
        sev = [x.motion_severity_smoothed or 0 for x in e]

        fig, ax = plt.subplots(figsize=(12, 3))
        ax.fill_between(times, sev, alpha=0.4, color="red")
        ax.plot(times, sev, lw=0.8, color="red")
        ax.set_ylim(0, 1)
        ax.set_ylabel("Motion severity")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        plt.suptitle("Motion Severity (inferred motion proxy)")
        plt.tight_layout()
        fig.savefig(self._dir / "plot_severity.png", dpi=100)
        plt.close(fig)

    def _plot_period(self, estimates: List[MotionEstimate]) -> None:
        e = self._decimate(estimates)
        times = [x.timestamp for x in e]
        rp = [x.dominant_roll_period for x in e]
        pp = [x.dominant_pitch_period for x in e]

        fig, ax = plt.subplots(figsize=(12, 3))
        ax.plot(
            times,
            [v if v is not None else float("nan") for v in rp],
            lw=0.8,
            label="Roll period (s)",
            color="steelblue",
        )
        ax.plot(
            times,
            [v if v is not None else float("nan") for v in pp],
            lw=0.8,
            label="Pitch period (s)",
            color="coral",
        )
        ax.set_ylabel("Period (s)")
        ax.legend()
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        plt.suptitle("Dominant Motion Period")
        plt.tight_layout()
        fig.savefig(self._dir / "plot_period.png", dpi=100)
        plt.close(fig)

    def _plot_roll_vs_wind(self, samples: List[InstantSample]) -> None:

        awa = [
            math.degrees(x.wind_angle_apparent)
            for x in samples
            if x.wind_angle_apparent is not None and x.roll is not None
        ]
        roll_rms_vals = [
            math.degrees(abs(x.roll))
            for x in samples
            if x.wind_angle_apparent is not None and x.roll is not None
        ]
        if len(awa) < 10:
            return

        fig, ax = plt.subplots(figsize=(7, 5))
        ax.scatter(awa, roll_rms_vals, s=3, alpha=0.3, color="steelblue")
        ax.set_xlabel("Apparent wind angle (deg)")
        ax.set_ylabel("|Roll| (deg)")
        ax.set_title("Roll magnitude vs Apparent Wind Angle")
        plt.tight_layout()
        fig.savefig(self._dir / "plot_roll_vs_wind.png", dpi=100)
        plt.close(fig)

    def _plot_pitch_vs_sog(self, samples: List[InstantSample]) -> None:

        sog = [x.sog for x in samples if x.sog is not None and x.pitch is not None]
        pitch_vals = [
            math.degrees(abs(x.pitch))
            for x in samples
            if x.sog is not None and x.pitch is not None
        ]
        if len(sog) < 10:
            return

        fig, ax = plt.subplots(figsize=(7, 5))
        ax.scatter(sog, pitch_vals, s=3, alpha=0.3, color="coral")
        ax.set_xlabel("SOG (m/s)")
        ax.set_ylabel("|Pitch| (deg)")
        ax.set_title("Pitch magnitude vs Speed Over Ground")
        plt.tight_layout()
        fig.savefig(self._dir / "plot_pitch_vs_sog.png", dpi=100)
        plt.close(fig)
