"""Tests for rolling-window feature extraction."""
from __future__ import annotations

import math
import sys
import os
import pytest
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from config import Config
from feature_extractor import FeatureExtractor
from models import InstantSample
from datetime import datetime, timezone, timedelta


def _ts(offset_s: float = 0.0) -> datetime:
    return datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_s)


def _make_samples(
    n: int,
    roll_fn=None,
    pitch_fn=None,
    fs: float = 2.0,
) -> list:
    """Create n InstantSamples spaced at 1/fs seconds."""
    dt = 1.0 / fs
    samples = []
    for i in range(n):
        t = i * dt
        roll = roll_fn(t) if roll_fn else 0.0
        pitch = pitch_fn(t) if pitch_fn else 0.0
        samples.append(
            InstantSample(
                timestamp=_ts(t),
                roll=roll,
                pitch=pitch,
                yaw=0.0,
                sog=3.0,
                heading=1.0,
                cog=1.0,
                rate_of_turn=0.0,
            )
        )
    return samples


# --------------------------------------------------------------------------- #
# Buffer sizes                                                                 #
# --------------------------------------------------------------------------- #

def test_buffer_fills_to_capacity():
    fs = 2.0
    config = Config(sample_rate_hz=fs, rolling_windows_s=[10])
    fe = FeatureExtractor(config)

    expected_cap = int(10 * fs)  # 20
    samples = _make_samples(expected_cap + 5, fs=fs)
    for s in samples:
        fe.add_sample(s)

    assert fe.buffer_fill(10) == expected_cap
    assert fe.buffer_capacity(10) == expected_cap


def test_buffer_does_not_grow_beyond_maxlen():
    fs = 2.0
    config = Config(sample_rate_hz=fs, rolling_windows_s=[10])
    fe = FeatureExtractor(config)
    samples = _make_samples(200, fs=fs)
    for s in samples:
        fe.add_sample(s)
    assert fe.buffer_fill(10) == int(10 * fs)


# --------------------------------------------------------------------------- #
# RMS calculation                                                              #
# --------------------------------------------------------------------------- #

def test_roll_rms_sine_wave():
    """RMS of a sine wave with amplitude A should be A/sqrt(2)."""
    fs = 2.0
    config = Config(sample_rate_hz=fs, rolling_windows_s=[60])
    fe = FeatureExtractor(config)

    amplitude = 0.2
    freq = 0.1
    samples = _make_samples(
        int(120 * fs),
        roll_fn=lambda t: amplitude * math.sin(2 * math.pi * freq * t),
        fs=fs,
    )
    for s in samples:
        fe.add_sample(s)

    wf = fe.get_window_features(60)
    assert wf is not None
    assert wf.roll_rms is not None
    expected_rms = amplitude / math.sqrt(2)
    assert wf.roll_rms == pytest.approx(expected_rms, rel=0.05)


def test_pitch_rms_constant():
    """RMS of a constant signal equals the absolute value."""
    fs = 2.0
    config = Config(sample_rate_hz=fs, rolling_windows_s=[30])
    fe = FeatureExtractor(config)

    value = 0.15
    samples = _make_samples(int(60 * fs), pitch_fn=lambda t: value, fs=fs)
    for s in samples:
        fe.add_sample(s)

    wf = fe.get_window_features(30)
    assert wf is not None
    assert wf.pitch_rms == pytest.approx(value, rel=0.01)
    assert wf.pitch_mean == pytest.approx(value, rel=0.01)
    assert wf.pitch_std == pytest.approx(0.0, abs=1e-6)


# --------------------------------------------------------------------------- #
# Peak-to-peak                                                                 #
# --------------------------------------------------------------------------- #

def test_roll_p2p_sine():
    fs = 2.0
    config = Config(sample_rate_hz=fs, rolling_windows_s=[30])
    fe = FeatureExtractor(config)

    amplitude = 0.3
    samples = _make_samples(
        int(60 * fs),
        roll_fn=lambda t: amplitude * math.sin(2 * math.pi * 0.1 * t),
        fs=fs,
    )
    for s in samples:
        fe.add_sample(s)

    wf = fe.get_window_features(30)
    assert wf is not None
    assert wf.roll_p2p is not None
    # p2p should be close to 2 * amplitude
    assert wf.roll_p2p == pytest.approx(2 * amplitude, rel=0.05)


# --------------------------------------------------------------------------- #
# PSD dominant frequency                                                       #
# --------------------------------------------------------------------------- #

def test_dominant_frequency_recovered():
    """Dominant frequency should match injected sine frequency."""
    fs = 2.0
    config = Config(sample_rate_hz=fs, rolling_windows_s=[60], psd_min_samples=16)
    fe = FeatureExtractor(config)

    target_freq = 0.1  # Hz → period 10 s
    samples = _make_samples(
        int(120 * fs),
        roll_fn=lambda t: 0.2 * math.sin(2 * math.pi * target_freq * t),
        fs=fs,
    )
    for s in samples:
        fe.add_sample(s)

    wf = fe.get_window_features(60)
    assert wf is not None
    assert wf.roll_dominant_freq is not None
    assert abs(wf.roll_dominant_freq - target_freq) < 0.03
    assert wf.roll_dominant_period == pytest.approx(1.0 / target_freq, rel=0.10)


# --------------------------------------------------------------------------- #
# Insufficient data returns None                                               #
# --------------------------------------------------------------------------- #

def test_no_features_before_sufficient_data():
    config = Config(sample_rate_hz=2.0, rolling_windows_s=[30])
    fe = FeatureExtractor(config)
    # Push only 2 samples – not enough for 30-s window (need ≥ 25% full)
    fe.add_sample(InstantSample(timestamp=_ts(0.0), roll=0.1))
    fe.add_sample(InstantSample(timestamp=_ts(0.5), roll=0.1))
    wf = fe.get_window_features(30)
    assert wf is None


# --------------------------------------------------------------------------- #
# Motion severity                                                              #
# --------------------------------------------------------------------------- #

def test_motion_severity_increases_with_roll():
    fs = 2.0
    config = Config(sample_rate_hz=fs, rolling_windows_s=[10, 30, 60, 300])
    fe_calm = FeatureExtractor(config)
    fe_heavy = FeatureExtractor(config)

    calm_samples = _make_samples(
        int(120 * fs),
        roll_fn=lambda t: 0.02 * math.sin(2 * math.pi * 0.1 * t),  # tiny roll
        fs=fs,
    )
    heavy_samples = _make_samples(
        int(120 * fs),
        roll_fn=lambda t: 0.30 * math.sin(2 * math.pi * 0.1 * t),  # large roll
        fs=fs,
    )

    for s in calm_samples:
        fe_calm.add_sample(s)
    for s in heavy_samples:
        fe_heavy.add_sample(s)

    me_calm = fe_calm.get_motion_estimate(window_s=60)
    me_heavy = fe_heavy.get_motion_estimate(window_s=60)

    assert me_calm is not None
    assert me_heavy is not None
    severity_calm = me_calm.motion_severity or 0.0
    severity_heavy = me_heavy.motion_severity or 0.0
    assert severity_heavy > severity_calm


def test_calm_regime_label():
    fs = 2.0
    config = Config(sample_rate_hz=fs, rolling_windows_s=[10, 30, 60, 300])
    fe = FeatureExtractor(config)

    # Very small roll/pitch → calm
    samples = _make_samples(
        int(120 * fs),
        roll_fn=lambda t: 0.005 * math.sin(2 * math.pi * 0.1 * t),
        pitch_fn=lambda t: 0.003 * math.sin(2 * math.pi * 0.08 * t),
        fs=fs,
    )
    for s in samples:
        fe.add_sample(s)

    me = fe.get_motion_estimate(window_s=60)
    assert me is not None
    assert me.motion_regime == "calm"


# --------------------------------------------------------------------------- #
# Yaw-rate variance                                                            #
# --------------------------------------------------------------------------- #

def test_yaw_rate_var_nonzero():
    fs = 2.0
    config = Config(sample_rate_hz=fs, rolling_windows_s=[30])
    fe = FeatureExtractor(config)
    rng = np.random.default_rng(0)
    n = int(60 * fs)
    timestamps = [_ts(i / fs) for i in range(n)]
    samples = [
        InstantSample(
            timestamp=timestamps[i],
            roll=0.0,
            pitch=0.0,
            rate_of_turn=float(rng.normal(0, 0.01)),
        )
        for i in range(n)
    ]
    for s in samples:
        fe.add_sample(s)

    wf = fe.get_window_features(30)
    assert wf is not None
    assert wf.yaw_rate_var is not None
    assert wf.yaw_rate_var > 0
