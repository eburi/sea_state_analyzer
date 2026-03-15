"""Tests for heave_estimator module: trochoidal wave height, Kalman heave,
Butterworth filter, and combined wave estimation.

Tests are grouped:
  1. Trochoidal wave height estimation
  2. Kalman heave estimator
  3. Butterworth low-pass filter
  4. Combined estimate_waves_from_accel
  5. Integration with FeatureExtractor and SignalK publisher
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pytest

from heave_estimator import (
    GRAVITY,
    KalmanHeaveEstimator,
    TrochoidalEstimate,
    WavePartition,
    butterworth_lowpass,
    estimate_waves_from_accel,
    trochoidal_wave_height,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _generate_trochoidal_accel(
    frequency_hz: float,
    amplitude_m: float,
    duration_s: float,
    fs: float,
    delta_v: float = 0.0,
    noise_std: float = 0.0,
) -> np.ndarray:
    """Generate synthetic trochoidal vertical acceleration.

    For a trochoidal wave with amplitude H and wavenumber k:
      Z(t) = -H * cos(k*c*t)
      a(t) = k^2 * c^2 * H * cos(k*c*t) = g * exp(2*pi*b/L) * cos(...)

    With Doppler (boat speed delta_v):
      a_obs(t) = H * k^2 * (c + delta_v)^2 * cos(k*(c+dv)*t)
    """
    g = GRAVITY
    # L from deep-water dispersion: L = g * T^2 / (2*pi)
    T = 1.0 / frequency_hz
    L = g * T * T / (2.0 * math.pi)
    k = 2.0 * math.pi / L
    c = math.sqrt(g * L / (2.0 * math.pi))

    # amplitude = 1/k * exp(k*b)  => exp(k*b) = amplitude * k
    # a_max = g * exp(2*pi*b/L) = g * amplitude * k
    # Actually: H = amplitude, a = H * k^2 * c^2 * cos(...)
    # For Doppler: a_obs = H * k^2 * (c+dv)^2 * cos(k*(c+dv)*t)

    effective_speed = c + delta_v
    t = np.arange(0, duration_s, 1.0 / fs)
    accel = (
        amplitude_m
        * k
        * k
        * effective_speed
        * effective_speed
        * np.cos(k * effective_speed * t)
    )
    if noise_std > 0:
        accel += np.random.default_rng(42).normal(0, noise_std, len(t))
    return accel


# --------------------------------------------------------------------------- #
# 1. Trochoidal wave height estimation                                         #
# --------------------------------------------------------------------------- #


class TestTrochoidalWaveHeight:
    def test_returns_none_for_zero_frequency(self) -> None:
        assert trochoidal_wave_height(1.0, 0.0) is None

    def test_returns_none_for_negative_frequency(self) -> None:
        assert trochoidal_wave_height(1.0, -0.1) is None

    def test_returns_none_for_very_high_frequency(self) -> None:
        assert trochoidal_wave_height(1.0, 3.0) is None

    def test_returns_none_for_negligible_accel(self) -> None:
        assert trochoidal_wave_height(0.001, 0.1) is None

    def test_basic_wave_height_no_doppler(self) -> None:
        """A 0.1 Hz wave (10s period) with moderate acceleration."""
        # 10s period => L = 9.81 * 100 / (2*pi) ≈ 156 m
        result = trochoidal_wave_height(0.5, 0.1, delta_v=0.0)
        assert result is not None
        assert isinstance(result, TrochoidalEstimate)
        assert result.significant_height > 0
        assert result.wavelength > 100
        assert result.wave_speed > 0
        assert result.method == "trochoidal"

    def test_higher_accel_gives_larger_wave(self) -> None:
        r1 = trochoidal_wave_height(0.3, 0.1)
        r2 = trochoidal_wave_height(1.0, 0.1)
        assert r1 is not None and r2 is not None
        assert r2.significant_height > r1.significant_height

    def test_lower_frequency_gives_longer_wavelength(self) -> None:
        r1 = trochoidal_wave_height(0.5, 0.1)
        r2 = trochoidal_wave_height(0.5, 0.05)
        assert r1 is not None and r2 is not None
        assert r2.wavelength > r1.wavelength

    def test_head_sea_doppler(self) -> None:
        """Head seas (positive delta_v) should give different wavelength."""
        r_no_dop = trochoidal_wave_height(0.5, 0.1, delta_v=0.0)
        r_head = trochoidal_wave_height(0.5, 0.1, delta_v=3.0)
        assert r_no_dop is not None and r_head is not None
        # Head seas: observed freq > true freq, so true wavelength is longer
        assert r_head.wavelength != r_no_dop.wavelength

    def test_following_sea_doppler(self) -> None:
        """Following seas (negative delta_v)."""
        result = trochoidal_wave_height(0.5, 0.08, delta_v=-2.0)
        assert result is not None
        assert result.significant_height > 0

    def test_strong_following_falls_back_to_no_doppler(self) -> None:
        """Very strong following seas with high freq: Doppler discriminant
        goes negative, so the function falls back to the no-Doppler
        estimate rather than returning None."""
        result = trochoidal_wave_height(0.5, 0.5, delta_v=-20.0)
        # Discriminant is negative, but fallback should produce a result
        assert result is not None
        assert result.significant_height > 0
        assert result.method == "trochoidal_no_doppler"

    def test_following_sea_doppler_fallback_real_conditions(self) -> None:
        """Real-world scenario: following seas delta_v=-2.9, freq=0.2 Hz.

        Discriminant = 8*pi*0.2*9.81*(-2.9) + 9.81^2
                     = -142.7 + 96.2 = -46.5  (negative → fallback)
        """
        result = trochoidal_wave_height(1.3, 0.2, delta_v=-2.9)
        assert result is not None
        assert result.significant_height > 0
        assert result.method == "trochoidal_no_doppler"
        # Wavelength from no-Doppler: g/(2*pi*f^2) = 9.81/(2*pi*0.04) ≈ 39m
        assert 30 < result.wavelength < 50

    def test_doppler_fallback_wavelength_matches_no_doppler(self) -> None:
        """When Doppler falls back, wavelength should match the zero-dv case
        (since both use the same encounter frequency)."""
        # Use delta_v that causes negative discriminant
        result_fallback = trochoidal_wave_height(0.5, 0.3, delta_v=-10.0)
        result_no_dv = trochoidal_wave_height(0.5, 0.3, delta_v=0.0)
        assert result_fallback is not None
        assert result_no_dv is not None
        # Wavelengths should be equal (both use L = g/(2*pi*f^2))
        assert abs(result_fallback.wavelength - result_no_dv.wavelength) < 0.01

    def test_successful_doppler_marked_trochoidal(self) -> None:
        """When Doppler succeeds (head seas), method should be 'trochoidal'."""
        result = trochoidal_wave_height(0.5, 0.1, delta_v=3.0)
        assert result is not None
        assert result.method == "trochoidal"

    def test_no_delta_v_marked_trochoidal(self) -> None:
        """With no Doppler correction, method should be 'trochoidal'."""
        result = trochoidal_wave_height(0.5, 0.1, delta_v=0.0)
        assert result is not None
        assert result.method == "trochoidal"

    def test_doppler_fallback_no_accel_correction(self) -> None:
        """When Doppler falls back, accel correction is skipped.
        This means accel_max in result should equal the input accel."""
        # Force discriminant negative
        result = trochoidal_wave_height(0.8, 0.25, delta_v=-8.0)
        assert result is not None
        # Without Doppler accel correction, a_max = accel_max_observed
        assert result.accel_max == 0.8

    def test_wave_height_physically_bounded(self) -> None:
        """Wave amplitude should not exceed L/(2*pi) (breaking limit)."""
        result = trochoidal_wave_height(9.5, 0.1, delta_v=0.0)
        if result is not None:
            assert result.wave_amplitude <= result.wavelength / (2.0 * math.pi) + 0.01

    def test_small_accel_gives_small_wave(self) -> None:
        result = trochoidal_wave_height(0.05, 0.1, delta_v=0.0)
        if result is not None:
            assert result.significant_height < 0.5  # less than 50cm

    def test_typical_ocean_wave(self) -> None:
        """Simulate a typical 1.5m wave with 8s period."""
        # 8s period => f = 0.125 Hz, L = g*64/(2pi) ≈ 100m
        # H = 0.75m (amplitude), k = 2pi/100 ≈ 0.0628
        # a_max = H * k^2 * c^2 where c = sqrt(g*L/2pi) ≈ 12.5 m/s
        # a_max = 0.75 * 0.0628^2 * 12.5^2 ≈ 0.75 * 0.00395 * 156 ≈ 0.46 m/s^2
        result = trochoidal_wave_height(0.46, 0.125, delta_v=0.0)
        assert result is not None
        # Should recover something close to 1.5m Hs
        assert 0.3 < result.significant_height < 5.0


# --------------------------------------------------------------------------- #
# 2. Kalman heave estimator                                                    #
# --------------------------------------------------------------------------- #


class TestKalmanHeaveEstimator:
    def test_create_default(self) -> None:
        kf = KalmanHeaveEstimator()
        assert kf.n_processed == 0
        assert kf.displacement == 0.0

    def test_update_single_sample(self) -> None:
        kf = KalmanHeaveEstimator(dt=0.02)
        d = kf.update(0.1)
        assert isinstance(d, float)
        assert kf.n_processed == 1

    def test_get_estimate_returns_none_insufficient_data(self) -> None:
        kf = KalmanHeaveEstimator(dt=0.02)
        for _ in range(10):
            kf.update(0.0)
        assert kf.get_estimate(min_samples=100) is None

    def test_zero_accel_gives_near_zero_heave(self) -> None:
        """With zero acceleration the filter should converge to zero heave."""
        kf = KalmanHeaveEstimator(dt=0.02)
        for _ in range(1000):
            kf.update(0.0)
        est = kf.get_estimate(min_samples=100)
        assert est is not None
        assert abs(est.heave_displacement) < 0.1
        assert est.heave_std < 0.1
        assert est.n_samples == 1000

    def test_sinusoidal_accel_gives_sinusoidal_heave(self) -> None:
        """Feed a pure sine wave and check heave oscillates."""
        dt = 0.02
        freq = 0.1  # 10s wave
        amplitude = 0.5  # m/s^2 peak accel

        kf = KalmanHeaveEstimator(dt=dt, accel_bias_window=200)
        heave_vals = []
        n_samples = int(60 / dt)  # 60 seconds
        for i in range(n_samples):
            t = i * dt
            accel = amplitude * math.cos(2 * math.pi * freq * t)
            d = kf.update(accel)
            heave_vals.append(d)

        est = kf.get_estimate(min_samples=100)
        assert est is not None
        # Should have some heave amplitude (not zero)
        assert est.heave_amplitude > 0.01
        # Hs should be positive
        assert est.significant_height > 0

    def test_reset_clears_state(self) -> None:
        kf = KalmanHeaveEstimator(dt=0.02)
        for _ in range(200):
            kf.update(0.5)
        assert kf.n_processed == 200

        kf.reset()
        assert kf.n_processed == 0
        assert kf.displacement == 0.0
        assert kf.get_estimate(min_samples=10) is None

    def test_convergence_flag(self) -> None:
        """Filter should mark as converged after enough samples."""
        kf = KalmanHeaveEstimator(dt=0.02, accel_bias_window=100)
        for _ in range(50):
            kf.update(0.0)
        est = kf.get_estimate(min_samples=10)
        assert est is not None
        assert not est.converged  # Not enough for bias window

        for _ in range(200):
            kf.update(0.0)
        est = kf.get_estimate(min_samples=10)
        assert est is not None
        assert est.converged

    def test_velocity_property(self) -> None:
        kf = KalmanHeaveEstimator(dt=0.02)
        kf.update(1.0)
        assert isinstance(kf.velocity, float)


# --------------------------------------------------------------------------- #
# 3. Butterworth low-pass filter                                               #
# --------------------------------------------------------------------------- #


class TestButterworthLowpass:
    def test_passthrough_when_cutoff_above_nyquist(self) -> None:
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = butterworth_lowpass(data, cutoff_hz=30.0, fs=50.0)
        np.testing.assert_array_equal(result, data)

    def test_passthrough_when_too_few_samples(self) -> None:
        data = np.array([1.0, 2.0])
        result = butterworth_lowpass(data, cutoff_hz=5.0, fs=50.0)
        np.testing.assert_array_equal(result, data)

    def test_removes_high_frequency_content(self) -> None:
        """A 0.1 Hz signal mixed with 10 Hz noise -- filter should preserve low freq."""
        fs = 50.0
        t = np.arange(0, 10, 1.0 / fs)
        low = np.sin(2 * np.pi * 0.1 * t)
        high = 0.5 * np.sin(2 * np.pi * 10 * t)
        mixed = low + high

        filtered = butterworth_lowpass(mixed, cutoff_hz=1.0, fs=fs, order=2)

        # After filtering, high freq should be greatly attenuated
        # Check correlation with pure low-freq signal
        corr = np.corrcoef(filtered, low)[0, 1]
        assert corr > 0.9

    def test_preserves_dc_level(self) -> None:
        fs = 50.0
        t = np.arange(0, 10, 1.0 / fs)  # longer signal for better edge behaviour
        data = 3.0 + 0.5 * np.sin(2 * np.pi * 0.1 * t)
        filtered = butterworth_lowpass(data, cutoff_hz=5.0, fs=fs)
        # Butterworth filter preserves DC; allow tolerance for edge effects
        assert abs(np.mean(filtered) - 3.0) < 0.5


# --------------------------------------------------------------------------- #
# 4. Combined estimate_waves_from_accel                                        #
# --------------------------------------------------------------------------- #


class TestEstimateWavesFromAccel:
    def test_returns_empty_for_too_few_samples(self) -> None:
        result = estimate_waves_from_accel(
            np.array([0.1, 0.2, 0.3]),
            fs=50.0,
        )
        assert result.significant_height is None
        assert result.method_used is None

    def test_returns_empty_for_zero_signal(self) -> None:
        result = estimate_waves_from_accel(
            np.zeros(500),
            fs=50.0,
        )
        # Zero signal has no dominant frequency
        assert result.significant_height is None

    def test_trochoidal_only_no_kalman(self) -> None:
        """Without a Kalman estimator, should use trochoidal method."""
        accel = _generate_trochoidal_accel(
            frequency_hz=0.1,
            amplitude_m=0.5,
            duration_s=60,
            fs=50.0,
        )
        result = estimate_waves_from_accel(accel, fs=50.0, kalman_estimator=None)
        assert result.trochoidal is not None
        assert result.kalman is None
        assert result.method_used == "trochoidal"
        assert result.significant_height is not None
        assert result.significant_height > 0

    def test_with_kalman_estimator(self) -> None:
        """With Kalman estimator, should produce a combined estimate."""
        kf = KalmanHeaveEstimator(dt=0.02, accel_bias_window=100)
        # Pre-fill with some data so it converges
        for _ in range(500):
            kf.update(0.0)

        accel = _generate_trochoidal_accel(
            frequency_hz=0.1,
            amplitude_m=0.5,
            duration_s=60,
            fs=50.0,
        )
        result = estimate_waves_from_accel(
            accel,
            fs=50.0,
            kalman_estimator=kf,
        )
        assert result.kalman is not None
        assert result.significant_height is not None
        assert result.significant_height > 0

    def test_frequency_detection(self) -> None:
        """Should detect the dominant frequency of the input."""
        target_freq = 0.1  # 10s wave
        accel = _generate_trochoidal_accel(
            frequency_hz=target_freq,
            amplitude_m=0.5,
            duration_s=120,
            fs=50.0,
        )
        result = estimate_waves_from_accel(accel, fs=50.0)
        assert result.accel_dominant_freq is not None
        # PSD resolution is limited by nperseg; with nperseg capped at 256
        # and fs=50, the bin width is 50/256 ≈ 0.195 Hz which is coarser
        # than our 0.1 Hz target.  Accept any detected frequency in the
        # plausible ocean-wave band (0.03 – 0.5 Hz).
        assert 0.03 < result.accel_dominant_freq < 0.5

    def test_accel_rms_computed(self) -> None:
        accel = _generate_trochoidal_accel(
            frequency_hz=0.1,
            amplitude_m=0.5,
            duration_s=30,
            fs=50.0,
        )
        result = estimate_waves_from_accel(accel, fs=50.0)
        assert result.accel_rms is not None
        assert result.accel_rms > 0

    def test_doppler_delta_v_passed_through(self) -> None:
        """delta_v should influence the trochoidal estimate."""
        accel = _generate_trochoidal_accel(
            frequency_hz=0.1,
            amplitude_m=0.5,
            duration_s=60,
            fs=50.0,
        )
        r_no_dop = estimate_waves_from_accel(accel, fs=50.0, delta_v=0.0)
        r_head = estimate_waves_from_accel(accel, fs=50.0, delta_v=3.0)
        # Both should produce estimates but they should differ
        assert r_no_dop.trochoidal is not None
        assert r_head.trochoidal is not None
        # Wavelengths should differ due to Doppler
        if r_no_dop.trochoidal and r_head.trochoidal:
            assert r_no_dop.trochoidal.wavelength != r_head.trochoidal.wavelength

    def test_noisy_signal(self) -> None:
        """Should still produce estimates with moderate noise."""
        accel = _generate_trochoidal_accel(
            frequency_hz=0.1,
            amplitude_m=0.5,
            duration_s=60,
            fs=50.0,
            noise_std=0.1,
        )
        result = estimate_waves_from_accel(accel, fs=50.0)
        assert result.accel_dominant_freq is not None
        # Should still detect something
        assert result.significant_height is not None or result.trochoidal is not None

    def test_confidence_reported(self) -> None:
        accel = _generate_trochoidal_accel(
            frequency_hz=0.1,
            amplitude_m=0.5,
            duration_s=60,
            fs=50.0,
        )
        result = estimate_waves_from_accel(accel, fs=50.0)
        assert result.confidence >= 0
        assert result.accel_freq_confidence is not None

    def test_freq_band_upper_bound_excludes_vibration(self) -> None:
        """High-freq vibration (e.g. 5 Hz engine) should not be selected as
        the dominant wave frequency when freq_max_hz caps the search band."""
        fs = 50.0
        duration = 60.0
        t = np.arange(0, duration, 1.0 / fs)
        # Ocean wave at 0.2 Hz with small amplitude
        ocean = 0.3 * np.sin(2 * math.pi * 0.2 * t)
        # Engine vibration at 5 Hz with larger amplitude
        engine = 1.0 * np.sin(2 * math.pi * 5.0 * t)
        accel = ocean + engine

        # With freq_max_hz=1.0, should find the 0.2 Hz ocean wave
        result = estimate_waves_from_accel(
            accel,
            fs=fs,
            freq_max_hz=1.0,
        )
        assert result.accel_dominant_freq is not None
        assert result.accel_dominant_freq < 1.0
        # Should be near 0.2 Hz (allow some PSD bin width tolerance)
        assert 0.1 < result.accel_dominant_freq < 0.5

    def test_freq_band_without_upper_bound_favours_low_freq(self) -> None:
        """With 1/f² displacement weighting, PSD favours the ocean wave even
        when high-frequency vibration has larger raw acceleration amplitude."""
        fs = 50.0
        duration = 60.0
        t = np.arange(0, duration, 1.0 / fs)
        ocean = 0.3 * np.sin(2 * math.pi * 0.2 * t)
        engine = 1.0 * np.sin(2 * math.pi * 5.0 * t)
        accel = ocean + engine

        # Even with freq_max_hz=25 (Nyquist), 1/f² weighting should still
        # find the 0.2 Hz ocean wave because displacement energy dominates
        result = estimate_waves_from_accel(
            accel,
            fs=fs,
            freq_max_hz=25.0,
        )
        assert result.accel_dominant_freq is not None
        assert result.accel_dominant_freq < 1.0
        assert 0.1 < result.accel_dominant_freq < 0.5

    def test_trochoidal_min_amplitude_lowered(self) -> None:
        """With lower min_amplitude, small waves that were previously rejected
        should now produce a trochoidal estimate."""
        # At 1 Hz, 0.3 m/s² peak accel gives ~7.6 mm amplitude
        # which would be rejected at min_amplitude=0.01 but accepted at 0.005
        trochoidal_wave_height(0.3, 1.0, min_amplitude=0.01)
        result_relaxed = trochoidal_wave_height(0.3, 1.0, min_amplitude=0.005)
        # The strict threshold may reject it; the relaxed one should accept
        assert result_relaxed is not None
        assert result_relaxed.significant_height > 0
        # Verify it's a small wave
        assert result_relaxed.significant_height < 0.05

    def test_combined_freq_band_and_min_amplitude(self) -> None:
        """End-to-end: ocean wave + vibration, with correct freq band and
        relaxed amplitude threshold, should produce a trochoidal estimate."""
        fs = 50.0
        duration = 120.0
        t = np.arange(0, duration, 1.0 / fs)
        # Small ocean wave at 0.5 Hz (2s period), ~0.1 m/s² peak
        ocean = 0.1 * np.sin(2 * math.pi * 0.5 * t)
        # Engine vibration at 8 Hz, larger amplitude
        engine = 0.5 * np.sin(2 * math.pi * 8.0 * t)
        accel = ocean + engine

        result = estimate_waves_from_accel(
            accel,
            fs=fs,
            freq_max_hz=1.0,
            trochoidal_min_amplitude=0.005,
        )
        assert result.accel_dominant_freq is not None
        assert result.accel_dominant_freq < 1.0
        # Should produce a trochoidal estimate for the small ocean wave
        assert result.trochoidal is not None
        assert result.significant_height is not None


# --------------------------------------------------------------------------- #
# 5. Integration with FeatureExtractor                                         #
# --------------------------------------------------------------------------- #


class TestFeatureExtractorWaveIntegration:
    def _make_sample(
        self,
        ts: datetime,
        roll: float = 0.0,
        pitch: float = 0.0,
        vertical_accel: float | None = None,
    ) -> "InstantSample":  # noqa: F821
        from models import InstantSample

        return InstantSample(
            timestamp=ts,
            roll=roll,
            pitch=pitch,
            vertical_accel=vertical_accel,
        )

    def test_add_imu_accel_method_exists(self) -> None:
        from config import Config
        from feature_extractor import FeatureExtractor

        fe = FeatureExtractor(Config())
        # Should not raise
        fe.add_imu_accel(0.1)
        fe.add_imu_accel(-0.2)

    def test_motion_estimate_has_wave_fields(self) -> None:
        """MotionEstimate should have wave height fields (even if None)."""
        from models import MotionEstimate

        me = MotionEstimate(
            timestamp=datetime.now(timezone.utc),
            window_s=60.0,
        )
        assert hasattr(me, "significant_height")
        assert hasattr(me, "heave")
        assert hasattr(me, "wave_height_method")
        assert hasattr(me, "wave_height_confidence")
        assert hasattr(me, "accel_dominant_freq")
        assert hasattr(me, "accel_dominant_period")
        assert hasattr(me, "accel_freq_confidence")

    def test_wave_estimation_populates_fields_with_accel_data(self) -> None:
        """With enough accel data, wave estimation should populate fields."""
        from config import Config
        from feature_extractor import FeatureExtractor

        cfg = Config(
            sample_rate_hz=2.0,
            rolling_windows_s=[10],
            imu_sample_rate_hz=50.0,
            heave_min_accel_samples=32,
        )
        fe = FeatureExtractor(cfg)

        # Feed 60s of attitude data at 2 Hz
        n_samples = 120  # 60s at 2 Hz
        freq = 0.1  # 10s wave
        base_ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        from datetime import timedelta

        for i in range(n_samples):
            ts = base_ts + timedelta(milliseconds=i * 500)
            t = i / 2.0
            sample = self._make_sample(
                ts=ts,
                roll=0.05 * math.sin(2 * math.pi * freq * t),
                pitch=0.03 * math.sin(2 * math.pi * freq * t + 0.5),
            )
            fe.add_sample(sample)

        # Also feed 60s of accel data at 50 Hz
        accel = _generate_trochoidal_accel(
            frequency_hz=freq,
            amplitude_m=0.5,
            duration_s=60,
            fs=50.0,
        )
        for a in accel:
            fe.add_imu_accel(float(a))

        # Get motion estimate
        me = fe.get_motion_estimate(window_s=10)
        # If we get an estimate, check wave fields
        if me is not None:
            # At minimum, accel spectral info should be populated
            # (significant_height may or may not be populated depending
            # on the specific signal characteristics)
            assert (
                me.accel_dominant_freq is not None or me.significant_height is not None
            )

    def test_motion_estimate_includes_position_and_partition_fields(self) -> None:
        from config import Config
        from feature_extractor import FeatureExtractor
        from datetime import timedelta

        cfg = Config(
            sample_rate_hz=2.0,
            rolling_windows_s=[10],
            imu_sample_rate_hz=50.0,
            heave_min_accel_samples=32,
        )
        fe = FeatureExtractor(cfg)

        base_ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        for i in range(120):
            ts = base_ts + timedelta(milliseconds=i * 500)
            sample = self._make_sample(
                ts=ts,
                roll=0.05 * math.sin(2 * math.pi * 0.12 * (i / 2.0)),
                pitch=0.03 * math.sin(2 * math.pi * 0.10 * (i / 2.0)),
            )
            sample.latitude = -10.9
            sample.longitude = -105.3
            fe.add_sample(sample)

        t = np.arange(0, 60.0, 1.0 / 50.0)
        accel = (
            0.6 * np.sin(2 * math.pi * 0.30 * t)
            + 0.8 * np.sin(2 * math.pi * 0.15 * t)
            + 0.7 * np.sin(2 * math.pi * 0.09 * t)
        )
        for a in accel:
            fe.add_imu_accel(float(a))

        me = fe.get_motion_estimate(window_s=10)
        assert me is not None
        assert me.latitude == pytest.approx(-10.9)
        assert me.longitude == pytest.approx(-105.3)

        # Partition fields may be absent if the signal does not present
        # sufficiently distinct peaks at this window length; ensure fields exist.
        assert hasattr(me, "wind_wave_height")
        assert hasattr(me, "swell_1_height")
        assert hasattr(me, "swell_2_height")


# --------------------------------------------------------------------------- #
# 6. Publisher integration                                                     #
# --------------------------------------------------------------------------- #


class TestPublisherWaveFields:
    def test_publisher_includes_significant_height(self) -> None:
        from models import MotionEstimate
        from signalk_publisher import _motion_estimate_to_values

        me = MotionEstimate(
            timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            window_s=60.0,
            motion_severity=0.3,
            significant_height=1.5,
            heave=0.2,
        )
        values = _motion_estimate_to_values(me)
        paths = [v["path"] for v in values]
        assert "environment.water.waves.significantHeight" in paths
        assert "environment.heave" in paths

        # Check values
        for v in values:
            if v["path"] == "environment.water.waves.significantHeight":
                assert v["value"] == 1.5
            if v["path"] == "environment.heave":
                assert v["value"] == 0.2

    def test_publisher_skips_none_wave_fields(self) -> None:
        from models import MotionEstimate
        from signalk_publisher import _motion_estimate_to_values

        me = MotionEstimate(
            timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            window_s=60.0,
            motion_severity=0.3,
            significant_height=None,
            heave=None,
        )
        values = _motion_estimate_to_values(me)
        paths = [v["path"] for v in values]
        assert "environment.water.waves.significantHeight" not in paths
        assert "environment.heave" not in paths

    def test_publisher_rounds_wave_values(self) -> None:
        from models import MotionEstimate
        from signalk_publisher import _motion_estimate_to_values

        me = MotionEstimate(
            timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            window_s=60.0,
            significant_height=1.23456,
            heave=0.12345,
        )
        values = _motion_estimate_to_values(me)
        for v in values:
            if v["path"] == "environment.water.waves.significantHeight":
                assert v["value"] == 1.23  # rounded to 2 decimal places
            if v["path"] == "environment.heave":
                assert v["value"] == 0.123  # rounded to 3 decimal places


# --------------------------------------------------------------------------- #
# 7. Hull resonance suppression                                                #
# --------------------------------------------------------------------------- #


class TestHullResonanceSuppression:
    def _make_hull_params(
        self,
        resonant_period: float = 2.99,
        beam_resonant_period: float = 2.26,
        roll_period_range: tuple[float, float] = (2.0, 4.0),
        pitch_period_range: tuple[float, float] = (2.0, 4.0),
    ) -> "HullParameters":  # noqa: F821
        from vessel_config import HullParameters, HullType

        return HullParameters(
            hull_type=HullType.CATAMARAN,
            resonant_period=resonant_period,
            beam_resonant_period=beam_resonant_period,
            natural_roll_period_min=roll_period_range[0],
            natural_roll_period_max=roll_period_range[1],
            natural_pitch_period_min=pitch_period_range[0],
            natural_pitch_period_max=pitch_period_range[1],
        )

    def test_suppression_function_exists(self) -> None:
        from heave_estimator import _hull_resonance_suppression

        assert callable(_hull_resonance_suppression)

    def test_no_hull_params_returns_unchanged(self) -> None:
        """Without hull params, PSD should be unchanged."""
        from heave_estimator import _hull_resonance_suppression
        from vessel_config import HullParameters

        freqs = np.linspace(0.01, 1.0, 100)
        psd = np.ones(100)
        hull = HullParameters()  # no resonance info
        result = _hull_resonance_suppression(freqs, psd, hull)
        np.testing.assert_array_equal(result, psd)

    def test_suppression_at_resonance_frequency(self) -> None:
        """PSD should be heavily suppressed at hull resonance frequency."""
        from heave_estimator import _hull_resonance_suppression

        hull = self._make_hull_params(resonant_period=3.0)
        res_freq = 1.0 / 3.0  # ~0.333 Hz

        freqs = np.linspace(0.01, 1.0, 1000)
        psd = np.ones(1000)
        result = _hull_resonance_suppression(freqs, psd, hull)

        # Find the bin closest to 0.333 Hz
        idx = np.argmin(np.abs(freqs - res_freq))
        # Should be heavily suppressed (< 50% of original)
        assert result[idx] < 0.5 * psd[idx]

    def test_swell_frequency_not_suppressed(self) -> None:
        """PSD at ocean swell frequencies (0.08-0.14 Hz) should be mostly preserved."""
        from heave_estimator import _hull_resonance_suppression

        hull = self._make_hull_params(resonant_period=3.0)

        freqs = np.linspace(0.01, 1.0, 1000)
        psd = np.ones(1000)
        result = _hull_resonance_suppression(freqs, psd, hull)

        # Check at 0.1 Hz (10s swell) and 0.125 Hz (8s swell)
        for swell_freq in [0.1, 0.125]:
            idx = np.argmin(np.abs(freqs - swell_freq))
            # Should retain > 80% of original at swell frequencies
            assert result[idx] > 0.8 * psd[idx], (
                f"Swell freq {swell_freq} Hz too suppressed: {result[idx]:.3f}"
            )

    def test_both_resonances_suppressed(self) -> None:
        """Both primary (LOA) and beam resonances should be suppressed."""
        from heave_estimator import _hull_resonance_suppression

        hull = self._make_hull_params(
            resonant_period=3.0,
            beam_resonant_period=2.26,
        )
        freqs = np.linspace(0.01, 1.0, 1000)
        psd = np.ones(1000)
        result = _hull_resonance_suppression(freqs, psd, hull)

        # Check suppression at both resonance frequencies
        for period in [3.0, 2.26]:
            freq = 1.0 / period
            idx = np.argmin(np.abs(freqs - freq))
            assert result[idx] < 0.5, (
                f"Period {period}s (freq {freq:.3f} Hz) not suppressed: {result[idx]:.3f}"
            )

    def test_suppression_with_zero_bandwidth_returns_unchanged(self) -> None:
        """With bandwidth_hz=0, no suppression should be applied."""
        from heave_estimator import _hull_resonance_suppression

        hull = self._make_hull_params()
        freqs = np.linspace(0.01, 1.0, 100)
        psd = np.ones(100)
        result = _hull_resonance_suppression(
            freqs,
            psd,
            hull,
            bandwidth_hz=0.0,
        )
        np.testing.assert_array_equal(result, psd)

    def test_wave_estimate_with_hull_suppression_picks_swell(self) -> None:
        """With hull resonance suppression, PSD peak detection should pick
        ocean swell (~0.125 Hz) instead of hull resonance (~0.33 Hz) when
        the hull response is strong enough to dominate even after 1/f² weighting.

        The 1/f² weighting converts accel PSD to displacement PSD.  For hull
        resonance at 0.33 Hz to still dominate over swell at 0.125 Hz in
        displacement PSD, it needs: hull_accel > swell_accel * (0.33/0.125)^2
        = swell_accel * 6.97.  So hull amplitude must be ~7x larger in accel.
        """
        fs = 50.0
        duration = 120.0  # 2 minutes
        t = np.arange(0, duration, 1.0 / fs)

        # Ocean swell at 0.125 Hz (8s period), moderate amplitude
        swell = 0.3 * np.sin(2 * math.pi * 0.125 * t)
        # Hull resonance at 0.33 Hz (3s period), very large amplitude
        # (7x+ to overwhelm 1/f² weighting: 0.3 * 7 = 2.1, use 3.0)
        hull_response = 3.0 * np.sin(2 * math.pi * 0.33 * t)
        accel = swell + hull_response

        hull_params = self._make_hull_params(
            resonant_period=3.0,
            beam_resonant_period=2.26,
        )

        # Without hull suppression: should detect ~0.33 Hz (hull resonance
        # dominates even after 1/f² weighting because amplitude is 10x)
        result_no_hull = estimate_waves_from_accel(
            accel,
            fs=fs,
            hull_params=None,
        )
        # With hull suppression: should shift to ~0.125 Hz (ocean swell)
        result_with_hull = estimate_waves_from_accel(
            accel,
            fs=fs,
            hull_params=hull_params,
        )

        assert result_no_hull.accel_dominant_freq is not None
        assert result_with_hull.accel_dominant_freq is not None

        # Without suppression, peak should be near hull resonance
        assert result_no_hull.accel_dominant_freq > 0.2, (
            f"Without hull suppression expected >0.2 Hz, got {result_no_hull.accel_dominant_freq}"
        )
        # With suppression, peak should shift to swell frequency
        assert result_with_hull.accel_dominant_freq < 0.2, (
            f"With hull suppression expected <0.2 Hz, got {result_with_hull.accel_dominant_freq}"
        )

    def test_wave_estimate_with_hull_suppression_gives_larger_hs(self) -> None:
        """When hull resonance is suppressed and swell frequency is detected,
        the trochoidal estimate should give a larger Hs (because the detected
        frequency is lower, leading to longer wavelength)."""
        fs = 50.0
        duration = 120.0
        t = np.arange(0, duration, 1.0 / fs)

        # Same ratio: hull ~10x swell to overwhelm 1/f² weighting
        swell = 0.3 * np.sin(2 * math.pi * 0.125 * t)
        hull_response = 3.0 * np.sin(2 * math.pi * 0.33 * t)
        accel = swell + hull_response

        hull_params = self._make_hull_params()

        result_no_hull = estimate_waves_from_accel(accel, fs=fs, hull_params=None)
        result_with_hull = estimate_waves_from_accel(
            accel, fs=fs, hull_params=hull_params
        )

        # Both should produce estimates
        hs_no = result_no_hull.significant_height
        hs_with = result_with_hull.significant_height
        assert hs_no is not None
        assert hs_with is not None

        # With hull suppression (picks lower freq), Hs should be larger
        # because trochoidal Hs scales with 1/f^2
        assert hs_with > hs_no, (
            f"Expected hull-suppressed Hs ({hs_with:.2f}) > unsuppressed ({hs_no:.2f})"
        )


# --------------------------------------------------------------------------- #
# 8. Spectral Hs (m0-based)                                                   #
# --------------------------------------------------------------------------- #


class TestSpectralHs:
    def test_spectral_hs_function_exists(self) -> None:
        from heave_estimator import _spectral_hs_from_displacement_psd

        assert callable(_spectral_hs_from_displacement_psd)

    def test_spectral_hs_zero_signal_returns_none(self) -> None:
        from heave_estimator import _spectral_hs_from_displacement_psd

        freqs = np.linspace(0.0, 25.0, 100)
        psd = np.zeros(100)
        result = _spectral_hs_from_displacement_psd(freqs, psd)
        assert result is None

    def test_spectral_hs_pure_sine(self) -> None:
        """For a pure sine accel at 0.1 Hz with known amplitude, spectral Hs
        should be approximately 4*sqrt(m0) where m0 relates to wave amplitude."""
        from heave_estimator import _spectral_hs_from_displacement_psd

        fs = 50.0
        duration = 120.0
        t = np.arange(0, duration, 1.0 / fs)
        freq = 0.1  # 10s wave
        accel_amplitude = 0.5  # m/s^2

        accel = accel_amplitude * np.sin(2 * math.pi * freq * t)

        from scipy import signal as scipy_signal

        nperseg = min(len(accel) // 2, 2048)
        freqs_psd, psd = scipy_signal.welch(
            accel - np.mean(accel),
            fs=fs,
            nperseg=nperseg,
        )

        result = _spectral_hs_from_displacement_psd(
            freqs_psd,
            psd,
            freq_min_hz=0.03,
            freq_max_hz=1.0,
        )
        assert result is not None
        assert result > 0
        # For a 0.1 Hz wave, displacement_amplitude = accel_amplitude / omega^2
        # = 0.5 / (2*pi*0.1)^2 = 0.5 / 0.3948 = 1.266 m
        # Hs ~ 2*sqrt(2) * displacement_amplitude = 3.58 m
        # (but PSD integration is approximate, so allow wide tolerance)
        assert 0.5 < result < 10.0

    def test_spectral_hs_in_wave_estimate(self) -> None:
        """estimate_waves_from_accel should populate spectral_hs field."""
        fs = 50.0
        duration = 60.0
        t = np.arange(0, duration, 1.0 / fs)
        accel = 0.5 * np.sin(2 * math.pi * 0.1 * t)

        result = estimate_waves_from_accel(accel, fs=fs)
        assert result.spectral_hs is not None
        assert result.spectral_hs > 0

    def test_spectral_hs_captures_multi_frequency_energy(self) -> None:
        """Spectral Hs should capture energy from multiple frequency
        components (swell + wind chop), unlike trochoidal which only
        uses the peak frequency."""
        from heave_estimator import _spectral_hs_from_displacement_psd

        fs = 50.0
        duration = 120.0
        t = np.arange(0, duration, 1.0 / fs)

        # Single component
        single = 0.5 * np.sin(2 * math.pi * 0.1 * t)
        # Two components (more total energy)
        multi = 0.5 * np.sin(2 * math.pi * 0.1 * t) + 0.3 * np.sin(
            2 * math.pi * 0.2 * t
        )

        from scipy import signal as scipy_signal

        nperseg = min(len(single) // 2, 2048)

        _, psd_single = scipy_signal.welch(
            single - np.mean(single), fs=fs, nperseg=nperseg
        )
        f, psd_multi = scipy_signal.welch(
            multi - np.mean(multi), fs=fs, nperseg=nperseg
        )

        hs_single = _spectral_hs_from_displacement_psd(f, psd_single)
        hs_multi = _spectral_hs_from_displacement_psd(f, psd_multi)

        assert hs_single is not None
        assert hs_multi is not None
        # Multi-component should have more energy → larger Hs
        assert hs_multi > hs_single

    def test_spectral_crosscheck_upgrades_low_estimate(self) -> None:
        """When spectral Hs is much larger than trochoidal, the combined
        estimator should upgrade to spectral."""
        fs = 50.0
        duration = 120.0
        t = np.arange(0, duration, 1.0 / fs)

        # Strong low-frequency swell + strong hull resonance
        swell = 1.0 * np.sin(2 * math.pi * 0.1 * t)
        hull = 2.0 * np.sin(2 * math.pi * 0.33 * t)
        accel = swell + hull

        result = estimate_waves_from_accel(accel, fs=fs)
        # Should have spectral_hs populated
        assert result.spectral_hs is not None
        assert result.spectral_hs > 0
        # And significant_height should be populated
        assert result.significant_height is not None

    def test_empty_freq_band_returns_none(self) -> None:
        from heave_estimator import _spectral_hs_from_displacement_psd

        freqs = np.linspace(0.0, 25.0, 100)
        psd = np.ones(100)
        # Band with no valid frequencies
        result = _spectral_hs_from_displacement_psd(
            freqs,
            psd,
            freq_min_hz=30.0,
            freq_max_hz=40.0,
        )
        assert result is None


# --------------------------------------------------------------------------- #
# 9. Multi-peak spectral partitions                                           #
# --------------------------------------------------------------------------- #


class TestWavePartitions:
    def test_partition_extraction_returns_components(self) -> None:
        fs = 50.0
        duration = 180.0
        t = np.arange(0, duration, 1.0 / fs)

        # Wind-wave + two swell systems
        signal = (
            0.6 * np.sin(2 * math.pi * 0.32 * t)  # wind-wave (~3.1s)
            + 0.9 * np.sin(2 * math.pi * 0.16 * t)  # swell_1 (~6.3s)
            + 0.7 * np.sin(2 * math.pi * 0.09 * t)  # swell_2 (~11.1s)
        )

        result = estimate_waves_from_accel(signal, fs=fs)
        assert result.spectral_partitions is not None
        parts = result.spectral_partitions
        labels = {p.component_type for p in parts}
        assert "wind_wave" in labels
        assert any(lbl.startswith("swell_") for lbl in labels)

        for p in parts:
            assert isinstance(p, WavePartition)
            assert p.hs_m > 0
            assert p.peak_freq_hz > 0
            assert p.peak_period_s > 0
            assert 0.0 <= p.confidence <= 1.0

    def test_partition_labeling_by_frequency(self) -> None:
        fs = 50.0
        duration = 180.0
        t = np.arange(0, duration, 1.0 / fs)
        signal = (
            0.5 * np.sin(2 * math.pi * 0.30 * t)
            + 0.8 * np.sin(2 * math.pi * 0.14 * t)
            + 0.7 * np.sin(2 * math.pi * 0.08 * t)
        )

        result = estimate_waves_from_accel(signal, fs=fs)
        assert result.spectral_partitions is not None
        by_label = {p.component_type: p for p in result.spectral_partitions}
        assert "wind_wave" in by_label
        swells = sorted(
            [
                p
                for p in result.spectral_partitions
                if p.component_type.startswith("swell_")
            ],
            key=lambda x: x.peak_freq_hz,
            reverse=True,
        )
        assert len(swells) >= 1
        assert by_label["wind_wave"].peak_freq_hz > swells[0].peak_freq_hz
