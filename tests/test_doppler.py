"""Tests for Doppler correction, new sensor fields, and validation guards."""
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
    doppler_correct,
    compute_delta_v,
    classify_wave_heading,
    _GRAVITY,
)
from models import InstantSample, SignalKValueUpdate
from state_store import SelfStateStore
from paths import (
    SPEED_THROUGH_WATER,
    WIND_DIRECTION_TRUE,
    CURRENT_DRIFT,
    CURRENT_SET_TRUE,
    RUDDER_ANGLE,
    AUTOPILOT_STATE,
    DEPTH_BELOW_TRANSDUCER,
)
from datetime import datetime, timezone, timedelta


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _ts(offset_s: float = 0.0) -> datetime:
    return datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_s)


def _make_update(path: str, value, received_at=None) -> SignalKValueUpdate:
    if received_at is None:
        received_at = datetime.now(timezone.utc)
    return SignalKValueUpdate(
        path=path, value=value, source="test",
        timestamp=received_at, received_at=received_at,
    )


def _sample(
    t: float = 0.0,
    roll: float = 0.0,
    pitch: float = 0.0,
    yaw: float = 0.0,
    sog: float = 3.0,
    heading: float = 0.0,
    cog: float = 0.0,
    stw: float | None = None,
    wind_angle_true: float | None = None,
    rudder_angle: float | None = None,
    depth: float | None = None,
) -> InstantSample:
    return InstantSample(
        timestamp=_ts(t),
        roll=roll, pitch=pitch, yaw=yaw,
        sog=sog, heading=heading, cog=cog,
        stw=stw, wind_angle_true=wind_angle_true,
        rudder_angle=rudder_angle, depth=depth,
    )


# =========================================================================== #
# A. doppler_correct() – pure math                                            #
# =========================================================================== #

class TestDopplerCorrectMath:

    def test_zero_delta_v_passthrough(self):
        """With delta_v ≈ 0, true period == encounter period."""
        enc_freq = 0.1  # 10 s encounter period
        result = doppler_correct(enc_freq, delta_v=0.0)
        assert result is not None
        T, L, c = result
        assert T == pytest.approx(10.0, rel=0.01)
        # Deep-water: L = g*T²/(2π)
        expected_L = _GRAVITY * T**2 / (2 * math.pi)
        assert L == pytest.approx(expected_L, rel=0.01)
        # Phase velocity: c = g*T/(2π)
        expected_c = _GRAVITY * T / (2 * math.pi)
        assert c == pytest.approx(expected_c, rel=0.01)

    def test_head_seas_longer_true_period(self):
        """Head seas (delta_v > 0): true period should be longer than encounter."""
        enc_freq = 0.15  # 6.67 s encounter period
        delta_v = 3.0    # 3 m/s head seas
        result = doppler_correct(enc_freq, delta_v)
        assert result is not None
        T, L, c = result
        # True period must be longer than encounter period in head seas
        assert T > 1.0 / enc_freq

    def test_following_seas_shorter_true_period(self):
        """Following seas (delta_v < 0): true period should be shorter than encounter."""
        enc_freq = 0.1   # 10 s encounter period
        delta_v = -2.0   # 2 m/s following seas
        result = doppler_correct(enc_freq, delta_v)
        assert result is not None
        T, L, c = result
        # True period must be shorter than encounter period in following seas
        assert T < 1.0 / enc_freq

    def test_wavelength_dispersion_consistency(self):
        """Verify L = g*T²/(2π) holds for all returned results."""
        for enc_freq in [0.05, 0.1, 0.15, 0.2]:
            for delta_v in [-2.0, 0.0, 1.0, 3.0]:
                result = doppler_correct(enc_freq, delta_v)
                if result is not None:
                    T, L, c = result
                    expected_L = _GRAVITY * T**2 / (2 * math.pi)
                    assert L == pytest.approx(expected_L, rel=1e-6), \
                        f"L mismatch at enc_freq={enc_freq}, delta_v={delta_v}"

    def test_phase_speed_consistency(self):
        """Verify c = L/T = g*T/(2π) for all returned results."""
        for enc_freq in [0.05, 0.1, 0.2]:
            for delta_v in [-1.5, 0.0, 2.5]:
                result = doppler_correct(enc_freq, delta_v)
                if result is not None:
                    T, L, c = result
                    assert c == pytest.approx(L / T, rel=1e-6)
                    assert c == pytest.approx(_GRAVITY * T / (2 * math.pi), rel=1e-6)

    def test_negative_encounter_freq_returns_none(self):
        assert doppler_correct(-0.1, 1.0) is None

    def test_zero_encounter_freq_returns_none(self):
        assert doppler_correct(0.0, 1.0) is None

    def test_infeasible_discriminant_returns_none(self):
        """Strong following seas with high encounter freq → negative discriminant."""
        # With corrected formula: disc = 1 + 4*(delta_v/g)*omega_e
        # For following seas (delta_v < 0) with high omega_e, discriminant goes negative.
        # disc = 1 + 4*(-10/9.8)*(2π*0.5) ≈ 1 - 12.8 = -11.8 < 0
        result = doppler_correct(0.5, -10.0)
        assert result is None

    def test_non_physical_period_rejected(self):
        """Periods outside 1-30 s range should be rejected."""
        # Very low encounter freq with large following seas
        # could produce a very short true period
        result = doppler_correct(0.01, -0.1)
        # encounter period = 100 s, with small following correction
        # true period > 30 s → should be rejected
        if result is not None:
            T, _, _ = result
            assert 1.0 <= T <= 30.0

    def test_known_10s_wave_head_seas(self):
        """
        Verify round-trip: given a 10s true wave, compute the encounter freq
        for a boat at 3 m/s head seas, then recover the true period.
        """
        g = _GRAVITY
        T_true = 10.0
        omega_true = 2 * math.pi / T_true
        k = omega_true**2 / g
        delta_v = 3.0  # head seas
        omega_e = omega_true + k * delta_v  # encounter angular freq
        enc_freq = omega_e / (2 * math.pi)

        result = doppler_correct(enc_freq, delta_v)
        assert result is not None
        T_recovered, L, c = result
        assert T_recovered == pytest.approx(T_true, rel=0.02)


# =========================================================================== #
# B. compute_delta_v() and classify_wave_heading()                             #
# =========================================================================== #

class TestComputeDeltaV:

    def test_head_wind_positive_delta_v(self):
        """Wind angle 0 (headwind) → delta_v = STW * cos(0) = STW."""
        dv = compute_delta_v(stw=3.0, wind_angle_true=0.0)
        assert dv is not None
        assert dv == pytest.approx(3.0)

    def test_following_wind_negative_delta_v(self):
        """Wind angle π (following wind) → delta_v = STW * cos(π) = -STW."""
        dv = compute_delta_v(stw=3.0, wind_angle_true=math.pi)
        assert dv is not None
        assert dv == pytest.approx(-3.0)

    def test_beam_wind_zero_delta_v(self):
        """Wind angle π/2 (beam) → delta_v ≈ 0."""
        dv = compute_delta_v(stw=3.0, wind_angle_true=math.pi / 2)
        assert dv is not None
        assert dv == pytest.approx(0.0, abs=1e-10)

    def test_quartering_wind(self):
        """Wind angle π/4 → delta_v = STW * cos(π/4)."""
        dv = compute_delta_v(stw=4.0, wind_angle_true=math.pi / 4)
        assert dv is not None
        assert dv == pytest.approx(4.0 * math.cos(math.pi / 4), rel=1e-6)

    def test_none_stw_returns_none(self):
        assert compute_delta_v(stw=None, wind_angle_true=0.0) is None

    def test_very_low_stw_returns_none(self):
        assert compute_delta_v(stw=0.05, wind_angle_true=0.0) is None

    def test_none_wind_angle_returns_none(self):
        assert compute_delta_v(stw=3.0, wind_angle_true=None) is None


class TestClassifyWaveHeading:

    def test_head(self):
        assert classify_wave_heading(3.0, 3.0) == "head"       # ratio=1.0

    def test_following(self):
        assert classify_wave_heading(-3.0, 3.0) == "following"  # ratio=-1.0

    def test_beam(self):
        assert classify_wave_heading(0.0, 3.0) == "beam"       # ratio=0.0

    def test_quartering_head(self):
        assert classify_wave_heading(1.5, 3.0) == "quartering_head"  # ratio=0.5

    def test_quartering_following(self):
        assert classify_wave_heading(-1.5, 3.0) == "quartering_following"  # ratio=-0.5

    def test_none_delta_v(self):
        assert classify_wave_heading(None, 3.0) is None

    def test_none_stw(self):
        assert classify_wave_heading(1.0, None) is None

    def test_low_stw(self):
        assert classify_wave_heading(0.05, 0.05) is None


# =========================================================================== #
# C. State store: new fields                                                   #
# =========================================================================== #

class TestStateStoreNewFields:

    def test_stw_populated(self):
        store = SelfStateStore(Config())
        store.apply_update_sync(_make_update(SPEED_THROUGH_WATER, 2.5))
        snap = store.snapshot()
        assert snap.stw == pytest.approx(2.5)

    def test_wind_direction_true_populated(self):
        store = SelfStateStore(Config())
        store.apply_update_sync(_make_update(WIND_DIRECTION_TRUE, 1.57))
        snap = store.snapshot()
        assert snap.wind_direction_true == pytest.approx(1.57)

    def test_current_drift_populated(self):
        store = SelfStateStore(Config())
        store.apply_update_sync(_make_update(CURRENT_DRIFT, 0.3))
        snap = store.snapshot()
        assert snap.current_drift == pytest.approx(0.3)

    def test_current_set_populated(self):
        store = SelfStateStore(Config())
        store.apply_update_sync(_make_update(CURRENT_SET_TRUE, 3.14))
        snap = store.snapshot()
        assert snap.current_set == pytest.approx(3.14)

    def test_rudder_angle_populated(self):
        store = SelfStateStore(Config())
        store.apply_update_sync(_make_update(RUDDER_ANGLE, -0.05))
        snap = store.snapshot()
        assert snap.rudder_angle == pytest.approx(-0.05)

    def test_autopilot_state_populated(self):
        store = SelfStateStore(Config())
        store.apply_update_sync(_make_update(AUTOPILOT_STATE, "wind"))
        snap = store.snapshot()
        assert snap.autopilot_state == "wind"

    def test_depth_populated(self):
        store = SelfStateStore(Config())
        store.apply_update_sync(_make_update(DEPTH_BELOW_TRANSDUCER, 25.0))
        snap = store.snapshot()
        assert snap.depth == pytest.approx(25.0)

    def test_freshness_tracked_for_new_fields(self):
        store = SelfStateStore(Config())
        store.apply_update_sync(_make_update(SPEED_THROUGH_WATER, 2.0))
        store.apply_update_sync(_make_update(DEPTH_BELOW_TRANSDUCER, 30.0))
        store.apply_update_sync(_make_update(RUDDER_ANGLE, 0.01))
        snap = store.snapshot()
        assert snap.field_valid["stw"] is True
        assert snap.field_valid["depth"] is True
        assert snap.field_valid["rudder_angle"] is True


# =========================================================================== #
# D. WindowFeatures: new rolling stats                                         #
# =========================================================================== #

def _make_samples_with_extras(
    n: int,
    fs: float = 2.0,
    roll_fn=None,
    pitch_fn=None,
    stw: float | None = None,
    wind_angle_true: float | None = None,
    rudder_angle: float | None = None,
    depth: float | None = None,
) -> list[InstantSample]:
    dt = 1.0 / fs
    samples = []
    for i in range(n):
        t = i * dt
        samples.append(InstantSample(
            timestamp=_ts(t),
            roll=roll_fn(t) if roll_fn else 0.01 * math.sin(0.6 * t),
            pitch=pitch_fn(t) if pitch_fn else 0.005 * math.sin(0.5 * t),
            yaw=0.0, sog=3.0, heading=1.0, cog=1.0,
            stw=stw,
            wind_angle_true=wind_angle_true,
            rudder_angle=rudder_angle,
            depth=depth,
        ))
    return samples


class TestWindowFeaturesNewStats:

    def test_stw_stats_computed(self):
        fs = 2.0
        config = Config(sample_rate_hz=fs, rolling_windows_s=[30])
        fe = FeatureExtractor(config)
        for s in _make_samples_with_extras(int(60 * fs), stw=3.5):
            fe.add_sample(s)
        wf = fe.get_window_features(30)
        assert wf is not None
        assert wf.stw_mean == pytest.approx(3.5, rel=0.01)
        assert wf.stw_std == pytest.approx(0.0, abs=1e-6)

    def test_rudder_angle_stats_computed(self):
        fs = 2.0
        config = Config(sample_rate_hz=fs, rolling_windows_s=[30])
        fe = FeatureExtractor(config)
        for s in _make_samples_with_extras(int(60 * fs), rudder_angle=0.02):
            fe.add_sample(s)
        wf = fe.get_window_features(30)
        assert wf is not None
        assert wf.rudder_angle_mean == pytest.approx(0.02, rel=0.01)
        assert wf.rudder_angle_std == pytest.approx(0.0, abs=1e-6)

    def test_depth_mean_computed(self):
        fs = 2.0
        config = Config(sample_rate_hz=fs, rolling_windows_s=[30])
        fe = FeatureExtractor(config)
        for s in _make_samples_with_extras(int(60 * fs), depth=50.0):
            fe.add_sample(s)
        wf = fe.get_window_features(30)
        assert wf is not None
        assert wf.depth_mean == pytest.approx(50.0, rel=0.01)

    def test_missing_stw_gives_none(self):
        fs = 2.0
        config = Config(sample_rate_hz=fs, rolling_windows_s=[30])
        fe = FeatureExtractor(config)
        for s in _make_samples_with_extras(int(60 * fs), stw=None):
            fe.add_sample(s)
        wf = fe.get_window_features(30)
        assert wf is not None
        assert wf.stw_mean is None
        assert wf.stw_std is None


# =========================================================================== #
# E. End-to-end Doppler correction in MotionEstimate                          #
# =========================================================================== #

def _make_doppler_samples(
    n: int,
    fs: float = 2.0,
    roll_freq: float = 0.1,
    roll_amp: float = 0.15,
    stw: float = 3.0,
    wind_angle_true: float = 0.5,
    rudder_angle: float = 0.01,
    depth: float = 100.0,
) -> list[InstantSample]:
    """Create samples with roll oscillation + STW/wind for Doppler correction."""
    dt = 1.0 / fs
    samples = []
    for i in range(n):
        t = i * dt
        samples.append(InstantSample(
            timestamp=_ts(t),
            roll=roll_amp * math.sin(2 * math.pi * roll_freq * t),
            pitch=0.03 * math.sin(2 * math.pi * 0.08 * t),
            yaw=0.0, sog=3.0, heading=1.0, cog=1.0,
            rate_of_turn=0.0,
            stw=stw,
            wind_angle_true=wind_angle_true,
            rudder_angle=rudder_angle,
            depth=depth,
        ))
    return samples


class TestEndToEndDoppler:

    def test_doppler_correction_produces_results(self):
        """With STW and wind angle data, MotionEstimate should have Doppler fields."""
        fs = 2.0
        config = Config(
            sample_rate_hz=fs,
            rolling_windows_s=[10, 30, 60, 300],
            psd_min_samples=16,
        )
        fe = FeatureExtractor(config)

        samples = _make_doppler_samples(
            int(120 * fs), fs=fs,
            roll_freq=0.1, roll_amp=0.15,
            stw=3.0, wind_angle_true=0.3,  # ~17 deg off bow, mostly head seas
            depth=200.0,  # deep enough for resulting wavelength (~217m → L/2 ≈ 108m)
        )
        for s in samples:
            fe.add_sample(s)

        me = fe.get_motion_estimate(window_s=60)
        assert me is not None
        assert me.encounter_period_estimate is not None

        # Doppler correction should have been applied
        assert me.doppler_delta_v is not None
        assert me.doppler_delta_v > 0  # head seas → positive delta_v
        assert me.true_wave_period is not None
        assert me.true_wavelength is not None
        assert me.wave_speed is not None
        assert me.doppler_correction_valid is True
        assert me.wave_heading is not None

    def test_doppler_true_period_longer_than_encounter_head_seas(self):
        """In head seas, true wave period > encounter period."""
        fs = 2.0
        config = Config(
            sample_rate_hz=fs,
            rolling_windows_s=[10, 30, 60, 300],
            psd_min_samples=16,
        )
        fe = FeatureExtractor(config)

        samples = _make_doppler_samples(
            int(120 * fs), fs=fs,
            roll_freq=0.1, roll_amp=0.20,
            stw=4.0, wind_angle_true=0.0,  # dead upwind → max head seas
            depth=200.0,
        )
        for s in samples:
            fe.add_sample(s)

        me = fe.get_motion_estimate(window_s=60)
        assert me is not None
        assert me.encounter_period_estimate is not None
        assert me.true_wave_period is not None
        assert me.true_wave_period > me.encounter_period_estimate

    def test_no_doppler_without_stw(self):
        """Without STW data, Doppler correction should not be attempted."""
        fs = 2.0
        config = Config(
            sample_rate_hz=fs,
            rolling_windows_s=[10, 30, 60, 300],
            psd_min_samples=16,
        )
        fe = FeatureExtractor(config)

        samples = _make_doppler_samples(
            int(120 * fs), fs=fs,
            roll_freq=0.1, roll_amp=0.15,
            stw=None,  # No STW
            wind_angle_true=0.3,
        )
        for s in samples:
            fe.add_sample(s)

        me = fe.get_motion_estimate(window_s=60)
        assert me is not None
        assert me.true_wave_period is None
        assert me.doppler_correction_valid is False

    def test_no_doppler_without_wind_angle(self):
        """Without wind angle, Doppler correction should not be attempted."""
        fs = 2.0
        config = Config(
            sample_rate_hz=fs,
            rolling_windows_s=[10, 30, 60, 300],
            psd_min_samples=16,
        )
        fe = FeatureExtractor(config)

        samples = _make_doppler_samples(
            int(120 * fs), fs=fs,
            roll_freq=0.1, roll_amp=0.15,
            stw=3.0,
            wind_angle_true=None,  # No wind angle
        )
        # wind_angle_true=None means compute_delta_v returns None for all samples
        for s in samples:
            fe.add_sample(s)

        me = fe.get_motion_estimate(window_s=60)
        assert me is not None
        assert me.true_wave_period is None
        assert me.doppler_correction_valid is False


# =========================================================================== #
# F. Validation guards                                                         #
# =========================================================================== #

class TestValidationGuards:

    def test_manoeuvre_suppresses_doppler(self):
        """Large rudder angle variation should suppress Doppler correction."""
        fs = 2.0
        config = Config(
            sample_rate_hz=fs,
            rolling_windows_s=[10, 30, 60, 300],
            psd_min_samples=16,
            doppler_rudder_std_max=0.10,
        )
        fe = FeatureExtractor(config)

        dt = 1.0 / fs
        n = int(120 * fs)
        samples = []
        for i in range(n):
            t = i * dt
            samples.append(InstantSample(
                timestamp=_ts(t),
                roll=0.15 * math.sin(2 * math.pi * 0.1 * t),
                pitch=0.03 * math.sin(2 * math.pi * 0.08 * t),
                yaw=0.0, sog=3.0, heading=1.0, cog=1.0,
                rate_of_turn=0.0,
                stw=3.0,
                wind_angle_true=0.3,
                # Large rudder oscillation → std >> 0.10 rad
                rudder_angle=0.30 * math.sin(2 * math.pi * 0.05 * t),
                depth=100.0,
            ))
        for s in samples:
            fe.add_sample(s)

        me = fe.get_motion_estimate(window_s=60)
        assert me is not None
        # Doppler correction should be suppressed
        assert me.true_wave_period is None
        assert me.doppler_correction_valid is False

    def test_low_stw_suppresses_doppler(self):
        """STW below doppler_min_stw should suppress Doppler correction."""
        fs = 2.0
        config = Config(
            sample_rate_hz=fs,
            rolling_windows_s=[10, 30, 60, 300],
            psd_min_samples=16,
            doppler_min_stw=0.5,
        )
        fe = FeatureExtractor(config)

        samples = _make_doppler_samples(
            int(120 * fs), fs=fs,
            roll_freq=0.1, roll_amp=0.15,
            stw=0.3,  # Below min threshold
            wind_angle_true=0.3,
            depth=100.0,
        )
        for s in samples:
            fe.add_sample(s)

        me = fe.get_motion_estimate(window_s=60)
        assert me is not None
        assert me.true_wave_period is None
        assert me.doppler_correction_valid is False

    def test_shallow_water_flags_invalid(self):
        """Shallow water should produce estimates but flag them as not valid."""
        fs = 2.0
        config = Config(
            sample_rate_hz=fs,
            rolling_windows_s=[10, 30, 60, 300],
            psd_min_samples=16,
        )
        fe = FeatureExtractor(config)

        samples = _make_doppler_samples(
            int(120 * fs), fs=fs,
            roll_freq=0.1, roll_amp=0.15,
            stw=3.0,
            wind_angle_true=0.3,
            depth=3.0,  # Very shallow — 3m < wavelength/2 for any ocean wave
        )
        for s in samples:
            fe.add_sample(s)

        me = fe.get_motion_estimate(window_s=60)
        assert me is not None

        if me.true_wave_period is not None:
            # Estimates were computed but flagged as invalid
            assert me.doppler_correction_valid is False
            # The values should still be present
            assert me.true_wavelength is not None
            assert me.wave_speed is not None

    def test_deep_water_flags_valid(self):
        """Deep water with good data should be flagged as valid."""
        fs = 2.0
        config = Config(
            sample_rate_hz=fs,
            rolling_windows_s=[10, 30, 60, 300],
            psd_min_samples=16,
        )
        fe = FeatureExtractor(config)

        samples = _make_doppler_samples(
            int(120 * fs), fs=fs,
            roll_freq=0.1, roll_amp=0.15,
            stw=3.0, wind_angle_true=0.3,
            rudder_angle=0.01,  # Steady rudder
            depth=200.0,        # Deep water
        )
        for s in samples:
            fe.add_sample(s)

        me = fe.get_motion_estimate(window_s=60)
        assert me is not None
        if me.true_wave_period is not None:
            assert me.doppler_correction_valid is True

    def test_steady_rudder_allows_doppler(self):
        """Small constant rudder angle should NOT suppress Doppler."""
        fs = 2.0
        config = Config(
            sample_rate_hz=fs,
            rolling_windows_s=[10, 30, 60, 300],
            psd_min_samples=16,
            doppler_rudder_std_max=0.10,
        )
        fe = FeatureExtractor(config)

        samples = _make_doppler_samples(
            int(120 * fs), fs=fs,
            roll_freq=0.1, roll_amp=0.15,
            stw=3.0, wind_angle_true=0.3,
            rudder_angle=0.05,  # Steady, small angle → std ≈ 0
            depth=200.0,
        )
        for s in samples:
            fe.add_sample(s)

        me = fe.get_motion_estimate(window_s=60)
        assert me is not None
        # Doppler correction should succeed
        assert me.true_wave_period is not None
        assert me.doppler_correction_valid is True

    def test_no_depth_data_still_valid(self):
        """Without depth data, shallow-water check is skipped → valid."""
        fs = 2.0
        config = Config(
            sample_rate_hz=fs,
            rolling_windows_s=[10, 30, 60, 300],
            psd_min_samples=16,
        )
        fe = FeatureExtractor(config)

        samples = _make_doppler_samples(
            int(120 * fs), fs=fs,
            roll_freq=0.1, roll_amp=0.15,
            stw=3.0, wind_angle_true=0.3,
            rudder_angle=0.01,
            depth=None,  # No depth sensor
        )
        for s in samples:
            fe.add_sample(s)

        me = fe.get_motion_estimate(window_s=60)
        assert me is not None
        if me.true_wave_period is not None:
            assert me.doppler_correction_valid is True
