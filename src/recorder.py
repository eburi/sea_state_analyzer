"""Data recorder.

Writes:
  raw_self_deltas.jsonl   – one JSON line per RawDeltaMessage
  samples.parquet         – normalized InstantSample rows
  features_<N>s.parquet   – WindowFeatures rows for each window size

Rows are batched in memory and flushed to Parquet periodically to avoid
excessive I/O and memory growth.  The JSONL file is flushed after each write.

All timestamps are stored as UTC ISO-8601 strings and as float Unix epoch
seconds for easy downstream use.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import Config, DEFAULT_CONFIG
from models import InstantSample, MotionEstimate, RawDeltaMessage, WindowFeatures

logger = logging.getLogger(__name__)


def _ts_str(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


def _ts_epoch(dt: Optional[datetime]) -> Optional[float]:
    if dt is None:
        return None
    return dt.timestamp()


# --------------------------------------------------------------------------- #
# Row converters                                                               #
# --------------------------------------------------------------------------- #

def _sample_to_row(s: InstantSample) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "timestamp": _ts_str(s.timestamp),
        "timestamp_epoch": _ts_epoch(s.timestamp),
        "roll": s.roll,
        "pitch": s.pitch,
        "yaw": s.yaw,
        "rate_of_turn": s.rate_of_turn,
        "sog": s.sog,
        "cog": s.cog,
        "heading": s.heading,
        "wind_speed_true": s.wind_speed_true,
        "wind_angle_true": s.wind_angle_true,
        "wind_speed_apparent": s.wind_speed_apparent,
        "wind_angle_apparent": s.wind_angle_apparent,
        "latitude": s.latitude,
        "longitude": s.longitude,
    }
    # Flatten field_ages and field_valid
    for k, v in s.field_ages.items():
        row[f"age_{k}"] = v
    for k, v in s.field_valid.items():
        row[f"valid_{k}"] = v
    return row


def _window_features_to_row(wf: WindowFeatures) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "timestamp": _ts_str(wf.timestamp),
        "timestamp_epoch": _ts_epoch(wf.timestamp),
        "window_s": wf.window_s,
        "n_samples": wf.n_samples,
        "roll_mean": wf.roll_mean,
        "roll_std": wf.roll_std,
        "roll_rms": wf.roll_rms,
        "roll_p2p": wf.roll_p2p,
        "roll_kurtosis": wf.roll_kurtosis,
        "roll_crest_factor": wf.roll_crest_factor,
        "roll_zero_crossing_period": wf.roll_zero_crossing_period,
        "roll_dominant_freq": wf.roll_dominant_freq,
        "roll_dominant_period": wf.roll_dominant_period,
        "roll_period_confidence": wf.roll_period_confidence,
        "roll_spectral_energy": wf.roll_spectral_energy,
        "pitch_mean": wf.pitch_mean,
        "pitch_std": wf.pitch_std,
        "pitch_rms": wf.pitch_rms,
        "pitch_p2p": wf.pitch_p2p,
        "pitch_kurtosis": wf.pitch_kurtosis,
        "pitch_crest_factor": wf.pitch_crest_factor,
        "pitch_zero_crossing_period": wf.pitch_zero_crossing_period,
        "pitch_dominant_freq": wf.pitch_dominant_freq,
        "pitch_dominant_period": wf.pitch_dominant_period,
        "pitch_period_confidence": wf.pitch_period_confidence,
        "pitch_spectral_energy": wf.pitch_spectral_energy,
        "yaw_rate_var": wf.yaw_rate_var,
        "sog_var": wf.sog_var,
        "heading_cog_var": wf.heading_cog_var,
        "wind_speed_var": wf.wind_speed_var,
        "wind_angle_var": wf.wind_angle_var,
        "spectral_entropy_roll": wf.spectral_entropy_roll,
        "spectral_entropy_pitch": wf.spectral_entropy_pitch,
        "roll_period_stability": wf.roll_period_stability,
        "pitch_period_stability": wf.pitch_period_stability,
    }
    # Flatten spectral band dicts
    if wf.spectral_bands_roll:
        for k, v in wf.spectral_bands_roll.items():
            row[f"roll_band_{k}"] = v
    if wf.spectral_bands_pitch:
        for k, v in wf.spectral_bands_pitch.items():
            row[f"pitch_band_{k}"] = v
    return row


def _motion_estimate_to_event(me: MotionEstimate) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "timestamp": _ts_str(me.timestamp),
        "timestamp_epoch": _ts_epoch(me.timestamp),
        "window_s": me.window_s,
        "motion_severity": me.motion_severity,
        "motion_severity_smoothed": me.motion_severity_smoothed,
        "motion_regime": me.motion_regime,
        "dominant_roll_period": me.dominant_roll_period,
        "dominant_pitch_period": me.dominant_pitch_period,
        "encounter_period_estimate": me.encounter_period_estimate,
        "period_confidence": me.period_confidence,
        "encounter_direction": me.encounter_direction,
        "direction_confidence": me.direction_confidence,
        "roll_dominant": me.roll_dominant,
        "motion_regularity": me.motion_regularity,
        "confusion_index": me.confusion_index,
        "comfort_proxy": me.comfort_proxy,
        "significant_height": me.significant_height,
        "heave": me.heave,
        "wave_height_method": me.wave_height_method,
        "wave_height_confidence": me.wave_height_confidence,
        "accel_dominant_freq": me.accel_dominant_freq,
        "accel_dominant_period": me.accel_dominant_period,
        "accel_freq_confidence": me.accel_freq_confidence,
        "severity_trend": me.severity_trend,
        "overall_confidence": me.overall_confidence,
    }
    # Strip None values for compact JSONL output
    return {k: v for k, v in d.items() if v is not None}


# --------------------------------------------------------------------------- #
# Recorder                                                                     #
# --------------------------------------------------------------------------- #

class Recorder:
    """
    Batched recorder for all pipeline outputs.

    Call open() before use and close() on shutdown.
    """

    def __init__(self, output_dir: Path, config: Config = DEFAULT_CONFIG) -> None:
        self._dir = output_dir
        self._config = config
        self._dir.mkdir(parents=True, exist_ok=True)

        self._jsonl_path = self._dir / "raw_self_deltas.jsonl"
        self._events_path = self._dir / "events.jsonl"
        self._samples_path = self._dir / "samples.parquet"

        # Per-window-size feature file paths
        self._feature_paths: Dict[int, Path] = {
            w: self._dir / f"features_{w}s.parquet"
            for w in config.rolling_windows_s
        }

        # Batch buffers
        self._sample_batch: List[Dict[str, Any]] = []
        self._feature_batches: Dict[int, List[Dict[str, Any]]] = {
            w: [] for w in config.rolling_windows_s
        }

        self._jsonl_fh = None
        self._events_fh = None
        self._total_samples = 0
        self._total_deltas = 0

    def open(self) -> None:
        self._jsonl_fh = open(self._jsonl_path, "a", encoding="utf-8")
        self._events_fh = open(self._events_path, "a", encoding="utf-8")
        logger.info("Recorder writing to %s", self._dir)

    def close(self) -> None:
        self._flush_samples()
        for w in self._config.rolling_windows_s:
            self._flush_features(w)
        if self._jsonl_fh:
            self._jsonl_fh.flush()
            self._jsonl_fh.close()
        if self._events_fh:
            self._events_fh.flush()
            self._events_fh.close()
        logger.info(
            "Recorder closed. Deltas=%d Samples=%d",
            self._total_deltas,
            self._total_samples,
        )

    # ------------------------------------------------------------------ #
    # Write methods                                                        #
    # ------------------------------------------------------------------ #

    def record_delta(self, delta: RawDeltaMessage) -> None:
        """Write a raw delta to JSONL immediately."""
        if self._jsonl_fh is None:
            return
        try:
            line = json.dumps(
                {
                    "received_at": _ts_str(delta.received_at),
                    "context": delta.context,
                    "raw": delta.raw,
                },
                default=str,
            )
            self._jsonl_fh.write(line + "\n")
            self._jsonl_fh.flush()
            self._total_deltas += 1
        except Exception as exc:
            logger.warning("Failed to write delta: %s", exc)

    def record_sample(self, sample: InstantSample) -> None:
        """Buffer a normalized sample; flush when batch is full."""
        self._sample_batch.append(_sample_to_row(sample))
        self._total_samples += 1
        if len(self._sample_batch) >= self._config.parquet_batch_size:
            self._flush_samples()

    def record_window_features(self, wf: WindowFeatures) -> None:
        """Buffer window features for the appropriate file."""
        w = int(wf.window_s)
        if w not in self._feature_batches:
            return
        self._feature_batches[w].append(_window_features_to_row(wf))
        if len(self._feature_batches[w]) >= self._config.parquet_batch_size:
            self._flush_features(w)

    def record_motion_estimate(self, me: MotionEstimate) -> None:
        """Write a motion estimate event to events JSONL."""
        if self._events_fh is None:
            return
        try:
            line = json.dumps(_motion_estimate_to_event(me), default=str)
            self._events_fh.write(line + "\n")
            self._events_fh.flush()
        except Exception as exc:
            logger.warning("Failed to write event: %s", exc)

    # ------------------------------------------------------------------ #
    # Flush helpers                                                        #
    # ------------------------------------------------------------------ #

    def _flush_samples(self) -> None:
        if not self._sample_batch:
            return
        self._append_parquet(self._samples_path, self._sample_batch)
        self._sample_batch = []

    def _flush_features(self, window_s: int) -> None:
        batch = self._feature_batches.get(window_s, [])
        if not batch:
            return
        path = self._feature_paths[window_s]
        self._append_parquet(path, batch)
        self._feature_batches[window_s] = []

    def flush_all(self) -> None:
        """Force-flush all pending batches."""
        self._flush_samples()
        for w in self._config.rolling_windows_s:
            self._flush_features(w)

    @staticmethod
    def _append_parquet(path: Path, rows: List[Dict[str, Any]]) -> None:
        """Append rows to a Parquet file (creates it if absent)."""
        try:
            df = pd.DataFrame(rows)
            table = pa.Table.from_pandas(df, preserve_index=False)
            if path.exists():
                existing = pq.read_table(str(path))
                # Align schemas by adding missing columns as null
                table = _align_schema(table, existing.schema)
                combined = pa.concat_tables([existing, table], promote=True)
                pq.write_table(combined, str(path), compression="snappy")
            else:
                pq.write_table(table, str(path), compression="snappy")
        except Exception as exc:
            logger.error("Failed to write Parquet to %s: %s", path, exc)


def _align_schema(
    table: pa.Table, target_schema: pa.Schema
) -> pa.Table:
    """Add missing columns (null-filled) to table so it matches target_schema."""
    for field in target_schema:
        if field.name not in table.schema.names:
            null_arr = pa.array([None] * len(table), type=field.type)
            table = table.append_column(field, null_arr)
    return table
