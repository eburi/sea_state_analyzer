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
)
from models import InstantSample
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
