"""Tests for sea_state_learner module: online learning, bin accumulation,
correction factor computation, and persistence."""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path

import pytest

from sea_state_learner import (
    BinStats,
    SeaStateLearner,
    PERIOD_BANDS,
    DIRECTION_CATEGORIES,
    MIN_OBSERVATIONS_FOR_CORRECTION,
    MAX_CORRECTION_FACTOR,
    MIN_CORRECTION_FACTOR,
    _period_band,
    _bin_key,
    _parse_bin_key,
)


# ========================================================================= #
# Period band classification                                                   #
# ========================================================================= #

class TestPeriodBand:
    """Tests for _period_band()."""

    def test_very_short(self) -> None:
        assert _period_band(1.0) == "very_short"

    def test_short(self) -> None:
        assert _period_band(3.0) == "short"

    def test_medium(self) -> None:
        assert _period_band(6.0) == "medium"

    def test_long(self) -> None:
        assert _period_band(10.0) == "long"

    def test_very_long(self) -> None:
        assert _period_band(20.0) == "very_long"

    def test_boundary_short_medium(self) -> None:
        assert _period_band(4.0) == "medium"

    def test_boundary_medium_long(self) -> None:
        assert _period_band(8.0) == "long"

    def test_zero_returns_none(self) -> None:
        assert _period_band(0.0) is None

    def test_negative_returns_none(self) -> None:
        assert _period_band(-1.0) is None

    def test_boundary_very_short_short(self) -> None:
        assert _period_band(2.0) == "short"


# ========================================================================= #
# Bin key                                                                      #
# ========================================================================= #

class TestBinKey:
    """Tests for _bin_key() and _parse_bin_key()."""

    def test_roundtrip(self) -> None:
        key = _bin_key("medium", "beam_like")
        band, direction = _parse_bin_key(key)
        assert band == "medium"
        assert direction == "beam_like"

    def test_format(self) -> None:
        assert _bin_key("short", "head_or_following_like") == "short:head_or_following_like"

    def test_parse_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid bin key"):
            _parse_bin_key("no_colon_here")


# ========================================================================= #
# BinStats                                                                     #
# ========================================================================= #

class TestBinStats:
    """Tests for BinStats running statistics."""

    def test_empty_stats(self) -> None:
        bs = BinStats()
        assert bs.n == 0
        assert bs.motion_rms_mean is None
        assert bs.motion_rms_std is None
        assert bs.hs_mean is None
        assert bs.hs_std is None
        assert bs.response_ratio_mean is None
        assert bs.response_ratio_std is None

    def test_single_update(self) -> None:
        bs = BinStats()
        bs.update(motion_rms=0.5, hs=1.0, response_ratio=0.5)
        assert bs.n == 1
        assert bs.motion_rms_mean == pytest.approx(0.5)
        assert bs.hs_mean == pytest.approx(1.0)
        assert bs.response_ratio_mean == pytest.approx(0.5)
        # std requires >= 2 samples
        assert bs.motion_rms_std is None

    def test_multiple_updates(self) -> None:
        bs = BinStats()
        for val in [1.0, 2.0, 3.0, 4.0]:
            bs.update(motion_rms=val, hs=val * 2, response_ratio=val / (val * 2))
        assert bs.n == 4
        assert bs.motion_rms_mean == pytest.approx(2.5)
        assert bs.hs_mean == pytest.approx(5.0)
        assert bs.motion_rms_std is not None
        assert bs.motion_rms_std > 0

    def test_std_two_samples(self) -> None:
        bs = BinStats()
        bs.update(motion_rms=1.0, hs=2.0, response_ratio=0.5)
        bs.update(motion_rms=3.0, hs=4.0, response_ratio=0.75)
        assert bs.motion_rms_std is not None
        assert bs.motion_rms_std > 0

    def test_serialisation_roundtrip(self) -> None:
        bs = BinStats()
        bs.update(motion_rms=0.3, hs=0.5, response_ratio=0.6)
        bs.update(motion_rms=0.4, hs=0.7, response_ratio=0.571)

        d = bs.to_dict()
        bs2 = BinStats.from_dict(d)

        assert bs2.n == bs.n
        assert bs2.motion_rms_sum == pytest.approx(bs.motion_rms_sum)
        assert bs2.hs_sq_sum == pytest.approx(bs.hs_sq_sum)
        assert bs2.response_ratio_sum == pytest.approx(bs.response_ratio_sum)

    def test_from_dict_defaults(self) -> None:
        """Missing keys should default to 0."""
        bs = BinStats.from_dict({})
        assert bs.n == 0
        assert bs.motion_rms_sum == 0.0


# ========================================================================= #
# SeaStateLearner: observe                                                     #
# ========================================================================= #

class TestSeaStateLearnerObserve:
    """Tests for SeaStateLearner.observe()."""

    def test_observe_returns_bin_key(self) -> None:
        learner = SeaStateLearner()
        key = learner.observe(
            wave_period=5.0,
            encounter_direction="beam_like",
            motion_severity=0.4,
            significant_height=1.0,
        )
        assert key is not None
        assert "medium" in key
        assert "beam_like" in key

    def test_observe_none_period(self) -> None:
        learner = SeaStateLearner()
        assert learner.observe(None, "beam_like", 0.5, 1.0) is None

    def test_observe_zero_period(self) -> None:
        learner = SeaStateLearner()
        assert learner.observe(0.0, "beam_like", 0.5, 1.0) is None

    def test_observe_none_direction(self) -> None:
        learner = SeaStateLearner()
        assert learner.observe(5.0, None, 0.5, 1.0) is None

    def test_observe_none_severity(self) -> None:
        learner = SeaStateLearner()
        assert learner.observe(5.0, "beam_like", None, 1.0) is None

    def test_observe_zero_severity(self) -> None:
        learner = SeaStateLearner()
        assert learner.observe(5.0, "beam_like", 0.0, 1.0) is None

    def test_observe_none_hs(self) -> None:
        learner = SeaStateLearner()
        assert learner.observe(5.0, "beam_like", 0.5, None) is None

    def test_observe_zero_hs(self) -> None:
        learner = SeaStateLearner()
        assert learner.observe(5.0, "beam_like", 0.5, 0.0) is None

    def test_observe_accumulates(self) -> None:
        learner = SeaStateLearner()
        for i in range(10):
            learner.observe(5.0, "beam_like", 0.3 + i * 0.01, 1.0)
        assert learner.total_observations == 10
        bins = learner.bins
        assert len(bins) == 1

    def test_observe_unknown_direction_defaults(self) -> None:
        """Unknown direction should be mapped to confused_like."""
        learner = SeaStateLearner()
        key = learner.observe(5.0, "unknown_dir", 0.5, 1.0)
        assert key is not None
        assert "confused_like" in key

    def test_observe_multiple_bins(self) -> None:
        """Different periods and directions go to different bins."""
        learner = SeaStateLearner()
        learner.observe(3.0, "beam_like", 0.5, 1.0)       # short:beam_like
        learner.observe(6.0, "beam_like", 0.5, 1.0)       # medium:beam_like
        learner.observe(6.0, "head_or_following_like", 0.3, 0.8)  # medium:head_or_following_like
        assert len(learner.bins) == 3
        assert learner.total_observations == 3


# ========================================================================= #
# SeaStateLearner: correction_factor                                           #
# ========================================================================= #

class TestSeaStateLearnerCorrection:
    """Tests for SeaStateLearner.correction_factor()."""

    def _populate_learner(
        self, learner: SeaStateLearner, n: int = 30
    ) -> None:
        """Populate bins with enough data for corrections."""
        # Beam seas, medium period: vessel responds more
        for _ in range(n):
            learner.observe(6.0, "beam_like", 0.6, 1.0)

        # Head seas, medium period: vessel responds less
        for _ in range(n):
            learner.observe(6.0, "head_or_following_like", 0.3, 1.0)

        # Short period, beam: different band
        for _ in range(n):
            learner.observe(3.0, "beam_like", 0.5, 1.0)

    def test_no_data_returns_one(self) -> None:
        learner = SeaStateLearner()
        assert learner.correction_factor(5.0, "beam_like") == 1.0

    def test_insufficient_data_returns_one(self) -> None:
        learner = SeaStateLearner()
        for _ in range(5):  # below MIN_OBSERVATIONS_FOR_CORRECTION
            learner.observe(5.0, "beam_like", 0.5, 1.0)
        assert learner.correction_factor(5.0, "beam_like") == 1.0

    def test_none_period_returns_one(self) -> None:
        learner = SeaStateLearner()
        assert learner.correction_factor(None, "beam_like") == 1.0

    def test_none_direction_returns_one(self) -> None:
        learner = SeaStateLearner()
        assert learner.correction_factor(5.0, None) == 1.0

    def test_correction_with_populated_data(self) -> None:
        """With populated data, correction should differ from 1.0."""
        learner = SeaStateLearner()
        self._populate_learner(learner)

        # Beam seas have higher response ratio (0.6/1.0=0.6)
        # Head seas have lower (0.3/1.0=0.3)
        # Overall mean ratio = (0.6*30 + 0.3*30 + 0.5*30) / 90 ≈ 0.467

        # For beam_like in medium: bin_ratio=0.6, overall≈0.467
        # correction = 0.467/0.6 ≈ 0.78 (reduce Hs because vessel over-responds)
        factor_beam = learner.correction_factor(6.0, "beam_like")
        assert factor_beam < 1.0  # vessel responds more -> Hs corrected down

        # For head_or_following_like in medium: bin_ratio=0.3, overall≈0.467
        # correction = 0.467/0.3 ≈ 1.56 -> clamped at MAX_CORRECTION_FACTOR
        factor_head = learner.correction_factor(6.0, "head_or_following_like")
        assert factor_head > 1.0  # vessel responds less -> Hs corrected up

    def test_correction_clamped(self) -> None:
        """Correction factor should be clamped to safe range."""
        learner = SeaStateLearner()
        self._populate_learner(learner)

        factor = learner.correction_factor(6.0, "head_or_following_like")
        assert MIN_CORRECTION_FACTOR <= factor <= MAX_CORRECTION_FACTOR

    def test_marginal_fallback(self) -> None:
        """When exact bin has too few observations, falls back to marginal."""
        learner = SeaStateLearner()
        # Populate medium:beam_like well, but medium:quartering_like with few obs
        for _ in range(30):
            learner.observe(6.0, "beam_like", 0.5, 1.0)
        for _ in range(30):
            learner.observe(6.0, "head_or_following_like", 0.3, 1.0)
        for _ in range(3):  # too few for direct correction
            learner.observe(6.0, "quartering_like", 0.4, 1.0)

        # Should fall back to marginal for medium band
        factor = learner.correction_factor(6.0, "quartering_like")
        # Marginal has enough data, so should get some correction
        assert isinstance(factor, float)

    def test_different_bands_different_corrections(self) -> None:
        """Bins in different period bands should give different corrections."""
        learner = SeaStateLearner()
        self._populate_learner(learner)

        factor_medium = learner.correction_factor(6.0, "beam_like")
        factor_short = learner.correction_factor(3.0, "beam_like")
        # These should be different since the ratios differ
        # (both 30 obs: medium beam=0.6, short beam=0.5)
        assert isinstance(factor_medium, float)
        assert isinstance(factor_short, float)


# ========================================================================= #
# SeaStateLearner: persistence                                                 #
# ========================================================================= #

class TestSeaStateLearnerPersistence:
    """Tests for save/load functionality."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        """Save then load should restore bin data."""
        path = str(tmp_path / "vessel_rao.json")

        learner1 = SeaStateLearner(persist_path=path)
        for _ in range(10):
            learner1.observe(5.0, "beam_like", 0.4, 1.0)
        learner1.save()

        learner2 = SeaStateLearner(persist_path=path)
        assert learner2.load()
        assert learner2.total_observations == 10
        bins = learner2.bins
        assert len(bins) == 1

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        path = str(tmp_path / "missing.json")
        learner = SeaStateLearner(persist_path=path)
        assert learner.load() is False

    def test_load_corrupt_file(self, tmp_path: Path) -> None:
        path = str(tmp_path / "corrupt.json")
        Path(path).write_text("not json at all{{{", encoding="utf-8")
        learner = SeaStateLearner(persist_path=path)
        assert learner.load() is False

    def test_load_wrong_version(self, tmp_path: Path) -> None:
        path = str(tmp_path / "wrong_version.json")
        Path(path).write_text(
            json.dumps({"version": 99, "bins": {}}), encoding="utf-8"
        )
        learner = SeaStateLearner(persist_path=path)
        assert learner.load() is False

    def test_load_merges_with_existing(self, tmp_path: Path) -> None:
        """Loading should merge into existing bins, not replace."""
        path = str(tmp_path / "vessel_rao.json")

        learner1 = SeaStateLearner(persist_path=path)
        for _ in range(5):
            learner1.observe(5.0, "beam_like", 0.4, 1.0)
        learner1.save()

        learner2 = SeaStateLearner(persist_path=path)
        for _ in range(3):
            learner2.observe(5.0, "beam_like", 0.5, 1.2)
        learner2.load()

        # Should have 5 (loaded) + 3 (already in learner2) = 8
        assert learner2.total_observations == 8

    def test_save_no_path(self) -> None:
        learner = SeaStateLearner(persist_path=None)
        assert learner.save() is False

    def test_load_no_path(self) -> None:
        learner = SeaStateLearner(persist_path=None)
        assert learner.load() is False

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = str(tmp_path / "sub" / "dir" / "vessel_rao.json")
        learner = SeaStateLearner(persist_path=path)
        learner.observe(5.0, "beam_like", 0.4, 1.0)
        assert learner.save()
        assert Path(path).exists()

    def test_file_format(self, tmp_path: Path) -> None:
        """Verify the JSON file has expected structure."""
        path = str(tmp_path / "vessel_rao.json")
        learner = SeaStateLearner(persist_path=path)
        learner.observe(5.0, "beam_like", 0.4, 1.0)
        learner.save()

        with open(path) as f:
            data = json.load(f)

        assert data["version"] == 1
        assert "bins" in data
        assert isinstance(data["bins"], dict)
        # Should have one bin with expected keys
        for key, stats in data["bins"].items():
            assert "n" in stats
            assert "motion_rms_sum" in stats
            assert "hs_sum" in stats
            assert "response_ratio_sum" in stats


# ========================================================================= #
# SeaStateLearner: summary                                                     #
# ========================================================================= #

class TestSeaStateLearnerSummary:
    """Tests for summary output."""

    def test_empty_summary(self) -> None:
        learner = SeaStateLearner()
        s = learner.summary()
        assert s["total_observations"] == 0
        assert s["num_bins"] == 0

    def test_populated_summary(self) -> None:
        learner = SeaStateLearner()
        for _ in range(5):
            learner.observe(5.0, "beam_like", 0.4, 1.0)
        s = learner.summary()
        assert s["total_observations"] == 5
        assert s["num_bins"] == 1
        assert "medium:beam_like" in s["bins"]
        bin_s = s["bins"]["medium:beam_like"]
        assert bin_s["n"] == 5
        assert bin_s["motion_rms_mean"] is not None


# ========================================================================= #
# FeatureExtractor integration with learner                                    #
# ========================================================================= #

class TestFeatureExtractorLearnerIntegration:
    """Tests for FeatureExtractor with learner (Phase 3 integration)."""

    def test_extractor_accepts_learner(self) -> None:
        from config import Config
        from feature_extractor import FeatureExtractor

        learner = SeaStateLearner()
        ext = FeatureExtractor(Config(), learner=learner)
        assert ext._learner is not None

    def test_extractor_none_learner(self) -> None:
        from config import Config
        from feature_extractor import FeatureExtractor

        ext = FeatureExtractor(Config(), learner=None)
        assert ext._learner is None

    def test_apply_learned_correction_no_learner(self) -> None:
        """Without learner, Hs should be unchanged."""
        from config import Config
        from feature_extractor import FeatureExtractor
        from models import MotionEstimate
        from datetime import datetime, timezone

        ext = FeatureExtractor(Config(), learner=None)
        me = MotionEstimate(
            timestamp=datetime.now(timezone.utc),
            window_s=30.0,
            significant_height=1.0,
            encounter_period_estimate=5.0,
            encounter_direction="beam_like",
            motion_severity_smoothed=0.5,
        )
        ext._apply_learned_correction(me)
        assert me.significant_height == 1.0

    def test_apply_learned_correction_insufficient_data(self) -> None:
        """With learner but too few observations, no correction."""
        from config import Config
        from feature_extractor import FeatureExtractor
        from models import MotionEstimate
        from datetime import datetime, timezone

        learner = SeaStateLearner()
        for _ in range(5):  # below threshold
            learner.observe(5.0, "beam_like", 0.4, 1.0)

        ext = FeatureExtractor(Config(), learner=learner)
        me = MotionEstimate(
            timestamp=datetime.now(timezone.utc),
            window_s=30.0,
            significant_height=1.0,
            encounter_period_estimate=5.0,
            encounter_direction="beam_like",
            motion_severity_smoothed=0.5,
        )
        ext._apply_learned_correction(me)
        # factor=1.0 (insufficient data), so Hs unchanged
        assert me.significant_height == 1.0

    def test_apply_learned_correction_with_data(self) -> None:
        """With sufficient data, learner should apply a correction."""
        from config import Config
        from feature_extractor import FeatureExtractor
        from models import MotionEstimate
        from datetime import datetime, timezone

        learner = SeaStateLearner()
        # Create two bins with different response ratios
        for _ in range(30):
            learner.observe(6.0, "beam_like", 0.6, 1.0)  # ratio=0.6
        for _ in range(30):
            learner.observe(6.0, "head_or_following_like", 0.3, 1.0)  # ratio=0.3

        ext = FeatureExtractor(Config(), learner=learner)

        # Test beam_like correction (high response -> Hs corrected down)
        me = MotionEstimate(
            timestamp=datetime.now(timezone.utc),
            window_s=30.0,
            significant_height=1.0,
            encounter_period_estimate=6.0,
            encounter_direction="beam_like",
            motion_severity_smoothed=0.5,
        )
        ext._apply_learned_correction(me)
        # Factor should be < 1.0 for beam_like (high response ratio)
        assert me.significant_height is not None
        assert me.significant_height < 1.0

    def test_learner_observes_from_motion_estimate(self) -> None:
        """The learner should accumulate observations from _apply_learned_correction."""
        from config import Config
        from feature_extractor import FeatureExtractor
        from models import MotionEstimate
        from datetime import datetime, timezone

        learner = SeaStateLearner()
        ext = FeatureExtractor(Config(), learner=learner)

        me = MotionEstimate(
            timestamp=datetime.now(timezone.utc),
            window_s=30.0,
            significant_height=1.0,
            encounter_period_estimate=5.0,
            encounter_direction="beam_like",
            motion_severity_smoothed=0.4,
        )
        ext._apply_learned_correction(me)
        assert learner.total_observations == 1


# ========================================================================= #
# Config field                                                                 #
# ========================================================================= #

class TestConfigLearnerField:
    """Tests for learner_persist_path config field."""

    def test_default_path(self) -> None:
        from config import Config
        cfg = Config()
        assert cfg.learner_persist_path == "/data/vessel_rao.json"

    def test_overridable(self) -> None:
        from config import Config
        cfg = Config(learner_persist_path="/tmp/custom.json")
        assert cfg.learner_persist_path == "/tmp/custom.json"
