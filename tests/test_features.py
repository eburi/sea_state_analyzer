"""Tests for feature extraction: derivatives, angle unwrapping, PSD."""

from __future__ import annotations

import math
import sys
import os
import pytest
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from config import Config
from feature_extractor import (
    FeatureExtractor,
    _unwrap_angle,
    _zero_crossing_period,
    _welch_dominant,
    _spectral_entropy,
    _spectral_energy_bands,
    _regime_label,
    _estimate_encounter_direction,
)
from models import InstantSample, WindowFeatures
from datetime import datetime, timezone, timedelta


def _ts(offset_s: float = 0.0) -> datetime:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return base + timedelta(seconds=offset_s)


def _sample(
    t: float = 0.0,
    roll: float = 0.0,
    pitch: float = 0.0,
    yaw: float = 0.0,
    sog: float = 3.0,
    heading: float = 0.0,
    cog: float = 0.0,
) -> InstantSample:
    return InstantSample(
        timestamp=_ts(t),
        roll=roll,
        pitch=pitch,
        yaw=yaw,
        sog=sog,
        heading=heading,
        cog=cog,
    )


# --------------------------------------------------------------------------- #
# Angle unwrapping                                                            #
# --------------------------------------------------------------------------- #


def test_unwrap_no_wrap_needed():
    prev = 0.1
    curr = 0.2
    result = _unwrap_angle(prev, curr)
    assert result == pytest.approx(0.2)


def test_unwrap_crossing_positive():
    """Value wrapping from ~π to ~-π should give a continuous +step."""
    prev = math.pi - 0.1
    curr = -(math.pi - 0.1)
    result = _unwrap_angle(prev, curr)
    # Should be approximately prev + 0.2
    assert result == pytest.approx(prev + 0.2, abs=1e-6)


def test_unwrap_crossing_negative():
    """Value wrapping from ~-π to ~+π should give a continuous -step."""
    prev = -(math.pi - 0.1)
    curr = math.pi - 0.1
    result = _unwrap_angle(prev, curr)
    assert result == pytest.approx(prev - 0.2, abs=1e-6)


def test_unwrap_first_sample():
    result = _unwrap_angle(None, 1.5)
    assert result == pytest.approx(1.5)


# --------------------------------------------------------------------------- #
# Zero-crossing period estimation                                              #
# --------------------------------------------------------------------------- #


def test_zero_crossing_period_sine():
    """Sine wave at 0.1 Hz sampled at 2 Hz should give ~10 s period."""
    fs = 2.0
    t = np.linspace(0, 60, int(60 * fs), endpoint=False)
    freq = 0.1
    x = np.sin(2 * math.pi * freq * t)
    period = _zero_crossing_period(x, fs)
    assert period is not None
    assert period == pytest.approx(1.0 / freq, rel=0.10)


def test_zero_crossing_too_few_samples():
    assert _zero_crossing_period(np.array([1.0, -1.0, 1.0]), 2.0) is None


def test_zero_crossing_flat_signal():
    x = np.ones(100)
    assert _zero_crossing_period(x, 2.0) is None


# --------------------------------------------------------------------------- #
# Welch PSD dominant frequency                                                 #
# --------------------------------------------------------------------------- #


def test_welch_dominant_sine():
    """Dominant frequency should match the injected sine frequency."""
    fs = 2.0
    duration = 60
    t = np.linspace(0, duration, int(duration * fs), endpoint=False)
    freq = 0.15
    x = np.sin(2 * math.pi * freq * t)
    dom_f, conf, freqs, psd = _welch_dominant(x, fs)
    assert dom_f is not None
    assert abs(dom_f - freq) < 0.05
    assert conf is not None and conf > 0.3


def test_welch_dominant_too_few():
    x = np.ones(4)
    dom_f, conf, freqs, psd = _welch_dominant(x, 2.0, min_samples=16)
    assert dom_f is None


def test_welch_dominant_white_noise():
    """White noise should return some frequency but low confidence."""
    rng = np.random.default_rng(42)
    x = rng.normal(0, 1, 256)
    dom_f, conf, freqs, psd = _welch_dominant(x, 2.0)
    assert dom_f is not None
    assert conf is not None and conf < 0.3


# --------------------------------------------------------------------------- #
# Spectral entropy                                                             #
# --------------------------------------------------------------------------- #


def test_spectral_entropy_flat():
    psd = np.ones(20)
    h = _spectral_entropy(psd)
    assert h == pytest.approx(math.log(20), rel=0.01)


def test_spectral_entropy_spike():
    psd = np.zeros(20)
    psd[5] = 1.0
    h = _spectral_entropy(psd)
    assert h == pytest.approx(0.0, abs=1e-6)


def test_spectral_entropy_flat_gt_spike():
    psd_flat = np.ones(20)
    psd_spike = np.zeros(20)
    psd_spike[5] = 1.0
    assert _spectral_entropy(psd_flat) > _spectral_entropy(psd_spike)


# --------------------------------------------------------------------------- #
# Derivative computation via FeatureExtractor                                  #
# --------------------------------------------------------------------------- #


def test_roll_rate_finite_difference():
    """roll_rate should match (roll[t] - roll[t-1]) / dt at sample rate."""
    config = Config(sample_rate_hz=2.0, derivative_filter_window=1)
    fe = FeatureExtractor(config)

    fe.add_sample(_sample(t=0.0, roll=0.0))
    la = fe.add_sample(_sample(t=0.5, roll=0.1))
    assert la.roll_rate is not None
    # Expected roll_rate = 0.1 / 0.5 = 0.2 rad/s
    assert la.roll_rate == pytest.approx(0.2, rel=0.05)


def test_pitch_rate_negative():
    config = Config(sample_rate_hz=2.0, derivative_filter_window=1)
    fe = FeatureExtractor(config)
    fe.add_sample(_sample(t=0.0, pitch=0.10))
    la = fe.add_sample(_sample(t=0.5, pitch=0.05))
    assert la.pitch_rate is not None
    # Expected pitch_rate = -0.05 / 0.5 = -0.1 rad/s
    assert la.pitch_rate == pytest.approx(-0.1, rel=0.05)


def test_heading_minus_cog():
    config = Config(sample_rate_hz=2.0)
    fe = FeatureExtractor(config)
    fe.add_sample(_sample(t=0.0, heading=1.0, cog=0.9))
    la = fe.add_sample(_sample(t=0.5, heading=1.0, cog=0.9))
    assert la.heading_minus_cog is not None
    assert la.heading_minus_cog == pytest.approx(0.1, abs=1e-6)


# --------------------------------------------------------------------------- #
# Regime labels                                                                #
# --------------------------------------------------------------------------- #


def test_regime_labels():
    assert _regime_label(0.0) == "calm"
    assert _regime_label(0.1) == "calm"
    assert _regime_label(0.3) == "moderate"
    assert _regime_label(0.5) == "active"
    assert _regime_label(0.8) == "heavy"
    assert _regime_label(1.0) == "heavy"


# --------------------------------------------------------------------------- #
# Spectral bands                                                               #
# --------------------------------------------------------------------------- #


def test_spectral_energy_bands_sum_to_one():
    freqs = np.linspace(0, 1, 200)
    psd = np.ones(200)
    bands = [(0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0)]
    result = _spectral_energy_bands(freqs, psd, bands)
    total = sum(result.values())
    assert total == pytest.approx(1.0, abs=0.05)


# --------------------------------------------------------------------------- #
# Encounter direction classification                                           #
# --------------------------------------------------------------------------- #


def _make_wf(
    roll_energy: float = 0.01,
    pitch_energy: float = 0.01,
    yaw_rate_var: float = 0.0,
    wind_angle_mean: float = None,
    wind_angle_var: float = None,
    spectral_entropy_roll: float = None,
    spectral_entropy_pitch: float = None,
    roll_period_stability: float = None,
    pitch_period_stability: float = None,
) -> WindowFeatures:
    """Helper to build a minimal WindowFeatures for direction tests."""
    return WindowFeatures(
        timestamp=_ts(),
        window_s=60.0,
        n_samples=120,
        roll_spectral_energy=roll_energy,
        pitch_spectral_energy=pitch_energy,
        yaw_rate_var=yaw_rate_var,
        wind_angle_mean=wind_angle_mean,
        wind_angle_var=wind_angle_var,
        spectral_entropy_roll=spectral_entropy_roll,
        spectral_entropy_pitch=spectral_entropy_pitch,
        roll_period_stability=roll_period_stability,
        pitch_period_stability=pitch_period_stability,
    )


# -- Wind-angle-based classification tests --


def test_direction_head_seas():
    """Wind from ahead (angle ~0) -> head_like."""
    wf = _make_wf(
        roll_energy=0.005,
        pitch_energy=0.02,
        wind_angle_mean=math.radians(10),
    )
    label, conf, roll_dom = _estimate_encounter_direction(wf)
    assert label == "head_like"
    assert conf > 0.0
    assert not roll_dom  # pitch dominant


def test_direction_following_seas():
    """Wind from astern (angle ~180°) -> following_like."""
    wf = _make_wf(
        roll_energy=0.005,
        pitch_energy=0.02,
        wind_angle_mean=math.radians(170),
    )
    label, conf, _ = _estimate_encounter_direction(wf)
    assert label == "following_like"


def test_direction_following_seas_negative_angle():
    """Wind from astern on port side (angle ~ -170°) -> following_like."""
    wf = _make_wf(
        roll_energy=0.005,
        pitch_energy=0.02,
        wind_angle_mean=math.radians(-170),
    )
    label, conf, _ = _estimate_encounter_direction(wf)
    assert label == "following_like"


def test_direction_aft_quarter_port():
    """Waves from 30° off the port stern -> following_quartering_like.

    This is the specific scenario the user observed: true wind angle
    relative to bow is ~150° (wind from aft, slightly to port).
    """
    wf = _make_wf(
        roll_energy=0.005,
        pitch_energy=0.015,
        wind_angle_mean=math.radians(150),
    )
    label, conf, _ = _estimate_encounter_direction(wf)
    assert label == "following_quartering_like"


def test_direction_aft_quarter_starboard():
    """Waves from 30° off the starboard stern -> following_quartering_like."""
    wf = _make_wf(
        roll_energy=0.005,
        pitch_energy=0.015,
        wind_angle_mean=math.radians(-150),
    )
    label, conf, _ = _estimate_encounter_direction(wf)
    assert label == "following_quartering_like"


def test_direction_beam_seas():
    """Wind abeam (angle ~90°) -> beam_like."""
    wf = _make_wf(
        roll_energy=0.02,
        pitch_energy=0.005,
        wind_angle_mean=math.radians(90),
    )
    label, conf, roll_dom = _estimate_encounter_direction(wf)
    assert label == "beam_like"
    assert roll_dom  # roll dominant


def test_direction_head_quarter():
    """Wind from 45° off the bow -> head_quartering_like."""
    wf = _make_wf(
        roll_energy=0.01,
        pitch_energy=0.015,
        wind_angle_mean=math.radians(45),
    )
    label, conf, _ = _estimate_encounter_direction(wf)
    assert label == "head_quartering_like"


def test_direction_spectral_consistency_boosts_confidence():
    """When spectral data agrees with wind angle, confidence is higher."""
    # Head seas with pitch-dominant energy (consistent)
    wf_consistent = _make_wf(
        roll_energy=0.005,
        pitch_energy=0.02,
        wind_angle_mean=math.radians(10),
    )
    _, conf_good, _ = _estimate_encounter_direction(wf_consistent)

    # Head seas with roll-dominant energy (inconsistent)
    wf_inconsistent = _make_wf(
        roll_energy=0.02,
        pitch_energy=0.005,
        wind_angle_mean=math.radians(10),
    )
    _, conf_bad, _ = _estimate_encounter_direction(wf_inconsistent)

    assert conf_good > conf_bad


def test_direction_high_wind_angle_var_reduces_confidence():
    """High wind angle variance should lower confidence."""
    wf_stable = _make_wf(
        roll_energy=0.01,
        pitch_energy=0.01,
        wind_angle_mean=math.radians(90),
        wind_angle_var=0.05,
    )
    _, conf_stable, _ = _estimate_encounter_direction(wf_stable)

    wf_variable = _make_wf(
        roll_energy=0.01,
        pitch_energy=0.01,
        wind_angle_mean=math.radians(90),
        wind_angle_var=1.0,
    )
    _, conf_variable, _ = _estimate_encounter_direction(wf_variable)

    assert conf_stable > conf_variable


# -- Spectral-only fallback tests (no wind angle) --


def test_direction_fallback_beam():
    """Strong roll energy, no wind -> beam_like."""
    wf = _make_wf(roll_energy=0.05, pitch_energy=0.005)
    label, conf, roll_dom = _estimate_encounter_direction(wf)
    assert label == "beam_like"
    assert roll_dom


def test_direction_fallback_head_or_following():
    """Strong pitch energy, low yaw, no wind -> head_or_following_like."""
    wf = _make_wf(roll_energy=0.005, pitch_energy=0.05, yaw_rate_var=0.0001)
    label, conf, _ = _estimate_encounter_direction(wf)
    assert label == "head_or_following_like"


def test_direction_fallback_quartering_from_pitch_dominant():
    """Strong pitch energy + high yaw variance -> quartering_like (fallback)."""
    wf = _make_wf(roll_energy=0.005, pitch_energy=0.05, yaw_rate_var=0.005)
    label, conf, _ = _estimate_encounter_direction(wf)
    assert label == "quartering_like"


def test_direction_fallback_quartering_from_roll_dominant():
    """Strong roll energy + high yaw variance -> quartering_like (fallback)."""
    wf = _make_wf(roll_energy=0.05, pitch_energy=0.005, yaw_rate_var=0.005)
    label, conf, _ = _estimate_encounter_direction(wf)
    assert label == "quartering_like"


def test_direction_zero_energy():
    """No spectral energy -> unknown."""
    wf = _make_wf(roll_energy=0.0, pitch_energy=0.0)
    label, conf, roll_dom = _estimate_encounter_direction(wf)
    assert label == "unknown"
    assert conf == 0.0
