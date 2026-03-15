"""Online sea-state learner: vessel-specific RAO transfer function.

Accumulates motion/wave observations into bins keyed by (wave period band,
encounter direction).  For each bin, running statistics are maintained:

- **n**: observation count
- **motion_rms_sum**, **motion_rms_sq_sum**: for mean/std of motion RMS
- **hs_sum**, **hs_sq_sum**: for mean/std of significant wave height
- **response_ratio_sum**, **response_ratio_sq_sum**: motion_rms / Hs ratio

Over time this builds a vessel-specific transfer function that can correct
Hs estimates beyond the static RAO model (Phase 2).

Persistence
-----------
The learned model is saved as JSON to a configurable path (default
``~/.sea_state_analyzer/vessel_rao.json``).  It is loaded on startup and saved periodically
or on shutdown.  The file format is a simple dict of bin-key -> stats.

Usage
-----
1. Create a ``SeaStateLearner`` and optionally ``load()`` a persisted model.
2. After each ``MotionEstimate``, call ``observe(me, wf)`` to accumulate.
3. Call ``correction_factor(period, direction)`` to get a learned
   multiplicative correction for Hs (1.0 = no correction).
4. Call ``save()`` periodically or on shutdown.

Thread safety: not thread-safe; designed for single-task asyncio use.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Period bands                                                                 #
# --------------------------------------------------------------------------- #

# Period bands in seconds: (label, lower_bound, upper_bound)
# Upper bound is exclusive except for the last band.
PERIOD_BANDS: List[Tuple[str, float, float]] = [
    ("very_short", 0.0, 2.0),
    ("short",      2.0, 4.0),
    ("medium",     4.0, 8.0),
    ("long",       8.0, 14.0),
    ("very_long",  14.0, float("inf")),
]

# Encounter direction categories (from feature extractor)
DIRECTION_CATEGORIES = [
    # Wind-angle-based labels (primary when wind data available)
    "head_like",
    "head_quartering_like",
    "beam_like",
    "following_quartering_like",
    "following_like",
    # Spectral-only fallback labels (when no wind angle)
    "head_or_following_like",
    "quartering_like",
    # Confusion / catch-all
    "confused_like",
    "mixed",
]


def _period_band(period_s: float) -> Optional[str]:
    """Map a wave period to its band label."""
    if period_s <= 0:
        return None
    for label, lo, hi in PERIOD_BANDS:
        if lo <= period_s < hi:
            return label
    return None


def _bin_key(period_band: str, direction: str) -> str:
    """Create a canonical bin key string."""
    return f"{period_band}:{direction}"


def _parse_bin_key(key: str) -> Tuple[str, str]:
    """Split a bin key back into (period_band, direction)."""
    parts = key.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid bin key: {key!r}")
    return parts[0], parts[1]


# --------------------------------------------------------------------------- #
# Bin statistics                                                               #
# --------------------------------------------------------------------------- #

@dataclass
class BinStats:
    """Running statistics for a single sea-state bin.

    Uses Welford-style incremental mean/variance for numerical stability.
    """
    n: int = 0
    motion_rms_sum: float = 0.0
    motion_rms_sq_sum: float = 0.0
    hs_sum: float = 0.0
    hs_sq_sum: float = 0.0
    response_ratio_sum: float = 0.0
    response_ratio_sq_sum: float = 0.0

    @property
    def motion_rms_mean(self) -> Optional[float]:
        return self.motion_rms_sum / self.n if self.n > 0 else None

    @property
    def motion_rms_std(self) -> Optional[float]:
        if self.n < 2:
            return None
        var = self.motion_rms_sq_sum / self.n - (self.motion_rms_sum / self.n) ** 2
        return math.sqrt(max(0.0, var))

    @property
    def hs_mean(self) -> Optional[float]:
        return self.hs_sum / self.n if self.n > 0 else None

    @property
    def hs_std(self) -> Optional[float]:
        if self.n < 2:
            return None
        var = self.hs_sq_sum / self.n - (self.hs_sum / self.n) ** 2
        return math.sqrt(max(0.0, var))

    @property
    def response_ratio_mean(self) -> Optional[float]:
        """Mean of motion_rms / Hs across observations."""
        return self.response_ratio_sum / self.n if self.n > 0 else None

    @property
    def response_ratio_std(self) -> Optional[float]:
        if self.n < 2:
            return None
        var = (
            self.response_ratio_sq_sum / self.n
            - (self.response_ratio_sum / self.n) ** 2
        )
        return math.sqrt(max(0.0, var))

    def update(
        self,
        motion_rms: float,
        hs: float,
        response_ratio: float,
    ) -> None:
        """Add one observation to this bin."""
        self.n += 1
        self.motion_rms_sum += motion_rms
        self.motion_rms_sq_sum += motion_rms * motion_rms
        self.hs_sum += hs
        self.hs_sq_sum += hs * hs
        self.response_ratio_sum += response_ratio
        self.response_ratio_sq_sum += response_ratio * response_ratio

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for JSON persistence."""
        return {
            "n": self.n,
            "motion_rms_sum": self.motion_rms_sum,
            "motion_rms_sq_sum": self.motion_rms_sq_sum,
            "hs_sum": self.hs_sum,
            "hs_sq_sum": self.hs_sq_sum,
            "response_ratio_sum": self.response_ratio_sum,
            "response_ratio_sq_sum": self.response_ratio_sq_sum,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BinStats":
        """Deserialise from a plain dict."""
        return cls(
            n=int(d.get("n", 0)),
            motion_rms_sum=float(d.get("motion_rms_sum", 0.0)),
            motion_rms_sq_sum=float(d.get("motion_rms_sq_sum", 0.0)),
            hs_sum=float(d.get("hs_sum", 0.0)),
            hs_sq_sum=float(d.get("hs_sq_sum", 0.0)),
            response_ratio_sum=float(d.get("response_ratio_sum", 0.0)),
            response_ratio_sq_sum=float(d.get("response_ratio_sq_sum", 0.0)),
        )


# --------------------------------------------------------------------------- #
# Minimum observations before a bin's learned correction is trusted            #
# --------------------------------------------------------------------------- #

MIN_OBSERVATIONS_FOR_CORRECTION = 20

# Maximum correction factor to apply (bounds for safety)
MAX_CORRECTION_FACTOR = 2.0
MIN_CORRECTION_FACTOR = 0.3


# --------------------------------------------------------------------------- #
# Sea State Learner                                                            #
# --------------------------------------------------------------------------- #

class SeaStateLearner:
    """Online learner that accumulates per-bin sea-state statistics.

    Call ``observe()`` after each MotionEstimate to accumulate data.
    Call ``correction_factor()`` to get a learned Hs correction.
    Call ``save()`` / ``load()`` for persistence.
    """

    def __init__(self, persist_path: Optional[str] = None) -> None:
        self._bins: Dict[str, BinStats] = {}
        self._persist_path: Optional[Path] = (
            Path(persist_path) if persist_path else None
        )
        self._observations_since_save: int = 0
        self._save_interval: int = 50  # save every N observations

    @property
    def bins(self) -> Dict[str, BinStats]:
        """Read-only access to bin statistics."""
        return dict(self._bins)

    @property
    def total_observations(self) -> int:
        """Total observations across all bins."""
        return sum(b.n for b in self._bins.values())

    def observe(
        self,
        wave_period: Optional[float],
        encounter_direction: Optional[str],
        motion_severity: Optional[float],
        significant_height: Optional[float],
    ) -> Optional[str]:
        """Record one observation into the appropriate bin.

        Parameters
        ----------
        wave_period : float or None
            Best available wave period (true or encounter), seconds.
        encounter_direction : str or None
            Direction category from feature extractor.
        motion_severity : float or None
            Motion severity (0-1) as a proxy for motion RMS.
        significant_height : float or None
            Estimated significant wave height, metres.

        Returns
        -------
        Bin key if observation was recorded, None if insufficient data.
        """
        if wave_period is None or wave_period <= 0:
            return None
        if encounter_direction is None:
            return None
        if motion_severity is None or motion_severity <= 0:
            return None
        if significant_height is None or significant_height <= 0:
            return None

        band = _period_band(wave_period)
        if band is None:
            return None

        # Normalise direction to known categories
        direction = encounter_direction if encounter_direction in DIRECTION_CATEGORIES else "confused_like"

        key = _bin_key(band, direction)

        if key not in self._bins:
            self._bins[key] = BinStats()

        response_ratio = motion_severity / significant_height
        self._bins[key].update(
            motion_rms=motion_severity,
            hs=significant_height,
            response_ratio=response_ratio,
        )

        self._observations_since_save += 1

        # Auto-save periodically
        if (
            self._persist_path is not None
            and self._observations_since_save >= self._save_interval
        ):
            self.save()
            self._observations_since_save = 0

        logger.debug(
            "SeaStateLearner: bin=%s n=%d ratio=%.3f",
            key, self._bins[key].n, response_ratio,
        )
        return key

    def correction_factor(
        self,
        wave_period: Optional[float],
        encounter_direction: Optional[str],
    ) -> float:
        """Get the learned Hs correction factor for a given period/direction.

        Returns a multiplicative factor to apply to the RAO-corrected Hs:
            Hs_final = Hs_rao_corrected * correction_factor

        When insufficient data exists for the exact bin, falls back to:
        1. Same period band, any direction (marginal)
        2. 1.0 (no correction)

        The correction is derived from the mean response ratio compared to
        the overall mean:
            correction = overall_mean_ratio / bin_mean_ratio

        If the vessel responds MORE in this bin than average (higher ratio),
        the Hs is corrected DOWN (the sea is calmer than the motion suggests).
        If it responds LESS, Hs is corrected UP.

        Returns
        -------
        Correction factor (clamped to [MIN_CORRECTION_FACTOR, MAX_CORRECTION_FACTOR]).
        """
        if wave_period is None or wave_period <= 0:
            return 1.0
        if encounter_direction is None:
            return 1.0

        band = _period_band(wave_period)
        if band is None:
            return 1.0

        direction = (
            encounter_direction
            if encounter_direction in DIRECTION_CATEGORIES
            else "confused_like"
        )
        key = _bin_key(band, direction)

        # Try exact bin first
        factor = self._compute_factor_for_key(key)
        if factor is not None:
            return factor

        # Fallback: marginalise over directions for this period band
        factor = self._compute_marginal_factor(band)
        if factor is not None:
            return factor

        return 1.0

    def _compute_factor_for_key(self, key: str) -> Optional[float]:
        """Compute correction factor for a specific bin key."""
        bin_stats = self._bins.get(key)
        if bin_stats is None or bin_stats.n < MIN_OBSERVATIONS_FOR_CORRECTION:
            return None

        bin_ratio = bin_stats.response_ratio_mean
        overall_ratio = self._overall_response_ratio_mean()

        if bin_ratio is None or overall_ratio is None:
            return None
        if bin_ratio <= 0 or overall_ratio <= 0:
            return None

        factor = overall_ratio / bin_ratio
        return float(max(MIN_CORRECTION_FACTOR, min(MAX_CORRECTION_FACTOR, factor)))

    def _compute_marginal_factor(self, period_band: str) -> Optional[float]:
        """Compute correction factor marginalised over directions."""
        total_n = 0
        weighted_ratio_sum = 0.0

        for key, stats in self._bins.items():
            try:
                band, _dir = _parse_bin_key(key)
            except ValueError:
                continue
            if band != period_band:
                continue
            if stats.n < 5:  # lower threshold for marginal
                continue
            ratio = stats.response_ratio_mean
            if ratio is not None and ratio > 0:
                weighted_ratio_sum += ratio * stats.n
                total_n += stats.n

        if total_n < MIN_OBSERVATIONS_FOR_CORRECTION:
            return None

        marginal_ratio = weighted_ratio_sum / total_n
        overall_ratio = self._overall_response_ratio_mean()

        if marginal_ratio <= 0 or overall_ratio is None or overall_ratio <= 0:
            return None

        factor = overall_ratio / marginal_ratio
        return float(max(MIN_CORRECTION_FACTOR, min(MAX_CORRECTION_FACTOR, factor)))

    def _overall_response_ratio_mean(self) -> Optional[float]:
        """Compute the overall mean response ratio across all bins."""
        total_n = 0
        total_sum = 0.0
        for stats in self._bins.values():
            if stats.n > 0:
                total_sum += stats.response_ratio_sum
                total_n += stats.n
        if total_n == 0:
            return None
        return total_sum / total_n

    # --- Persistence ------------------------------------------------------ #

    def save(self, path: Optional[str] = None) -> bool:
        """Save learned model to JSON file.

        Returns True on success, False on failure (logged, never raises).
        """
        target = Path(path) if path else self._persist_path
        if target is None:
            logger.debug("SeaStateLearner: no persist path configured, skipping save")
            return False

        try:
            data = {
                "version": 1,
                "bins": {k: v.to_dict() for k, v in self._bins.items()},
            }
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.info(
                "SeaStateLearner: saved %d bins (%d total obs) to %s",
                len(self._bins), self.total_observations, target,
            )
            return True
        except Exception as exc:
            logger.warning("SeaStateLearner: save failed: %s", exc)
            return False

    def load(self, path: Optional[str] = None) -> bool:
        """Load learned model from JSON file.

        Returns True on success, False on failure (logged, never raises).
        Merges loaded data into any existing bins (additive).
        """
        target = Path(path) if path else self._persist_path
        if target is None:
            logger.debug("SeaStateLearner: no persist path configured, skipping load")
            return False

        if not target.exists():
            logger.info("SeaStateLearner: no saved model at %s", target)
            return False

        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                logger.warning("SeaStateLearner: invalid format in %s", target)
                return False

            version = raw.get("version", 0)
            if version != 1:
                logger.warning(
                    "SeaStateLearner: unknown version %s in %s", version, target
                )
                return False

            bins_data = raw.get("bins", {})
            loaded = 0
            for key, stats_dict in bins_data.items():
                if not isinstance(stats_dict, dict):
                    continue
                loaded_stats = BinStats.from_dict(stats_dict)
                if key in self._bins:
                    # Merge: add loaded stats to existing
                    existing = self._bins[key]
                    existing.n += loaded_stats.n
                    existing.motion_rms_sum += loaded_stats.motion_rms_sum
                    existing.motion_rms_sq_sum += loaded_stats.motion_rms_sq_sum
                    existing.hs_sum += loaded_stats.hs_sum
                    existing.hs_sq_sum += loaded_stats.hs_sq_sum
                    existing.response_ratio_sum += loaded_stats.response_ratio_sum
                    existing.response_ratio_sq_sum += loaded_stats.response_ratio_sq_sum
                else:
                    self._bins[key] = loaded_stats
                loaded += 1

            logger.info(
                "SeaStateLearner: loaded %d bins (%d total obs) from %s",
                loaded, self.total_observations, target,
            )
            return True
        except Exception as exc:
            logger.warning("SeaStateLearner: load failed: %s", exc)
            return False

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict for logging/debugging."""
        bin_summaries = {}
        for key, stats in sorted(self._bins.items()):
            bin_summaries[key] = {
                "n": stats.n,
                "motion_rms_mean": round(stats.motion_rms_mean, 4)
                if stats.motion_rms_mean is not None
                else None,
                "hs_mean": round(stats.hs_mean, 4)
                if stats.hs_mean is not None
                else None,
                "response_ratio_mean": round(stats.response_ratio_mean, 4)
                if stats.response_ratio_mean is not None
                else None,
            }
        return {
            "total_observations": self.total_observations,
            "num_bins": len(self._bins),
            "bins": bin_summaries,
        }
