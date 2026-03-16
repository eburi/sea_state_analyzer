"""Tests for Douglas sea-state scale and Beaufort wind force classifications.

Tests cover:
- Douglas wind-sea (WMO Code 3700): all degree boundaries 0-9, edge cases
- Douglas swell (WMO Code 3701): height×wavelength matrix, period-to-wavelength
  derivation, missing wavelength fallback
- Beaufort wind force: all force boundaries 0-12, edge cases
- Convenience functions: douglas_degree_from_hs, douglas_label_from_hs,
  beaufort_force_from_wind, beaufort_label_from_wind
- Result dataclass immutability (frozen=True)
- Integration: publisher includes new fields, recorder includes new fields,
  metadata entries exist for all new publish paths
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

import pytest

from scales import (
    BeaufortForce,
    DouglasSeaState,
    DouglasSwellState,
    beaufort_force_from_wind,
    beaufort_label_from_wind,
    classify_beaufort,
    classify_douglas_sea_state,
    classify_douglas_swell,
    douglas_degree_from_hs,
    douglas_label_from_hs,
)
from models import MotionEstimate
from paths import (
    PUBLISH_PATHS,
    WAVE_BEAUFORT_FORCE,
    WAVE_BEAUFORT_LABEL,
    WAVE_DOUGLAS_SEA_STATE,
    WAVE_DOUGLAS_SEA_STATE_LABEL,
    WAVE_DOUGLAS_SWELL,
    WAVE_DOUGLAS_SWELL_LABEL,
    WAVE_PATH_META,
)
from signalk_publisher import _motion_estimate_to_values, build_delta_message
from recorder import _motion_estimate_to_event


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _make_estimate(**overrides: Any) -> MotionEstimate:
    """Create a MotionEstimate with sensible defaults for testing."""
    defaults = dict(
        timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        window_s=60.0,
    )
    defaults.update(overrides)
    return MotionEstimate(**defaults)


# --------------------------------------------------------------------------- #
# Douglas sea-state scale — wind-sea (WMO Code 3700)                         #
# --------------------------------------------------------------------------- #


class TestDouglasSeaState:
    """Douglas wind-sea classification from significant wave height."""

    # ---- None / invalid inputs ---- #

    def test_none_returns_none(self) -> None:
        assert classify_douglas_sea_state(None) is None

    def test_negative_returns_none(self) -> None:
        assert classify_douglas_sea_state(-0.5) is None

    def test_negative_tiny_returns_none(self) -> None:
        assert classify_douglas_sea_state(-0.001) is None

    # ---- Degree 0: exactly 0.0 (glassy) ---- #

    def test_degree_0_zero(self) -> None:
        r = classify_douglas_sea_state(0.0)
        assert r is not None
        assert r.degree == 0
        assert r.label == "Calm (glassy)"
        assert r.hs_m == 0.0

    # ---- Degree 1: > 0 and ≤ 0.10 m ---- #

    def test_degree_1_small(self) -> None:
        r = classify_douglas_sea_state(0.05)
        assert r is not None
        assert r.degree == 1
        assert r.label == "Calm (rippled)"

    def test_degree_1_at_boundary(self) -> None:
        r = classify_douglas_sea_state(0.10)
        assert r is not None
        assert r.degree == 1

    # ---- Degree 2: > 0.10 and ≤ 0.50 m ---- #

    def test_degree_2_mid(self) -> None:
        r = classify_douglas_sea_state(0.30)
        assert r is not None
        assert r.degree == 2
        assert r.label == "Smooth"

    def test_degree_2_at_boundary(self) -> None:
        r = classify_douglas_sea_state(0.50)
        assert r is not None
        assert r.degree == 2

    # ---- Degree 3: > 0.50 and ≤ 1.25 m ---- #

    def test_degree_3_mid(self) -> None:
        r = classify_douglas_sea_state(1.0)
        assert r is not None
        assert r.degree == 3
        assert r.label == "Slight"

    def test_degree_3_at_boundary(self) -> None:
        r = classify_douglas_sea_state(1.25)
        assert r is not None
        assert r.degree == 3

    # ---- Degree 4: > 1.25 and ≤ 2.50 m ---- #

    def test_degree_4_mid(self) -> None:
        r = classify_douglas_sea_state(2.0)
        assert r is not None
        assert r.degree == 4
        assert r.label == "Moderate"

    def test_degree_4_at_boundary(self) -> None:
        r = classify_douglas_sea_state(2.50)
        assert r is not None
        assert r.degree == 4

    # ---- Degree 5: > 2.50 and ≤ 4.00 m ---- #

    def test_degree_5_mid(self) -> None:
        r = classify_douglas_sea_state(3.5)
        assert r is not None
        assert r.degree == 5
        assert r.label == "Rough"

    def test_degree_5_at_boundary(self) -> None:
        r = classify_douglas_sea_state(4.00)
        assert r is not None
        assert r.degree == 5

    # ---- Degree 6: > 4.00 and ≤ 6.00 m ---- #

    def test_degree_6_mid(self) -> None:
        r = classify_douglas_sea_state(5.0)
        assert r is not None
        assert r.degree == 6
        assert r.label == "Very rough"

    def test_degree_6_at_boundary(self) -> None:
        r = classify_douglas_sea_state(6.00)
        assert r is not None
        assert r.degree == 6

    # ---- Degree 7: > 6.00 and ≤ 9.00 m ---- #

    def test_degree_7_mid(self) -> None:
        r = classify_douglas_sea_state(7.5)
        assert r is not None
        assert r.degree == 7
        assert r.label == "High"

    def test_degree_7_at_boundary(self) -> None:
        r = classify_douglas_sea_state(9.00)
        assert r is not None
        assert r.degree == 7

    # ---- Degree 8: > 9.00 and ≤ 14.00 m ---- #

    def test_degree_8_mid(self) -> None:
        r = classify_douglas_sea_state(12.0)
        assert r is not None
        assert r.degree == 8
        assert r.label == "Very high"

    def test_degree_8_at_boundary(self) -> None:
        r = classify_douglas_sea_state(14.00)
        assert r is not None
        assert r.degree == 8

    # ---- Degree 9: > 14.00 m (phenomenal) ---- #

    def test_degree_9_just_above(self) -> None:
        r = classify_douglas_sea_state(14.01)
        assert r is not None
        assert r.degree == 9
        assert r.label == "Phenomenal"

    def test_degree_9_extreme(self) -> None:
        r = classify_douglas_sea_state(25.0)
        assert r is not None
        assert r.degree == 9

    # ---- Result carries input value ---- #

    def test_result_carries_hs(self) -> None:
        r = classify_douglas_sea_state(3.14)
        assert r is not None
        assert r.hs_m == 3.14

    # ---- Frozen dataclass ---- #

    def test_result_is_frozen(self) -> None:
        r = classify_douglas_sea_state(2.0)
        assert r is not None
        with pytest.raises(AttributeError):
            r.degree = 99  # type: ignore[misc]

    # ---- Parametrized sweep across all boundaries ---- #

    @pytest.mark.parametrize(
        "hs, expected_degree",
        [
            (0.0, 0),
            (0.05, 1),
            (0.10, 1),
            (0.11, 2),
            (0.50, 2),
            (0.51, 3),
            (1.25, 3),
            (1.26, 4),
            (2.50, 4),
            (2.51, 5),
            (4.00, 5),
            (4.01, 6),
            (6.00, 6),
            (6.01, 7),
            (9.00, 7),
            (9.01, 8),
            (14.00, 8),
            (14.01, 9),
            (50.0, 9),
        ],
    )
    def test_boundary_sweep(self, hs: float, expected_degree: int) -> None:
        r = classify_douglas_sea_state(hs)
        assert r is not None
        assert r.degree == expected_degree, (
            f"Hs={hs} -> expected degree {expected_degree}, got {r.degree}"
        )


# --------------------------------------------------------------------------- #
# Douglas swell scale (WMO Code 3701)                                        #
# --------------------------------------------------------------------------- #


class TestDouglasSwell:
    """Douglas swell classification from height and wavelength/period."""

    # ---- None / invalid inputs ---- #

    def test_none_height_returns_none(self) -> None:
        assert classify_douglas_swell(None) is None

    def test_negative_height_returns_none(self) -> None:
        assert classify_douglas_swell(-1.0) is None

    # ---- Degree 0: zero height ---- #

    def test_degree_0_no_swell(self) -> None:
        r = classify_douglas_swell(0.0)
        assert r is not None
        assert r.degree == 0
        assert r.label == "No swell"
        assert r.height_m == 0.0

    def test_degree_0_with_wavelength(self) -> None:
        r = classify_douglas_swell(0.0, wavelength_m=150.0)
        assert r is not None
        assert r.degree == 0
        # Wavelength passed through even for zero height
        assert r.wavelength_m == 150.0

    # ---- Height < 2m (low), varying wavelength ---- #

    def test_low_short_degree_1(self) -> None:
        """Low height + short wavelength -> degree 1."""
        r = classify_douglas_swell(1.0, wavelength_m=50.0)
        assert r is not None
        assert r.degree == 1

    def test_low_average_degree_1(self) -> None:
        """Low height + average wavelength -> degree 1."""
        r = classify_douglas_swell(1.5, wavelength_m=150.0)
        assert r is not None
        assert r.degree == 1

    def test_low_long_degree_2(self) -> None:
        """Low height + long wavelength -> degree 2."""
        r = classify_douglas_swell(1.0, wavelength_m=250.0)
        assert r is not None
        assert r.degree == 2

    # ---- Height 2-4m (moderate), varying wavelength ---- #

    def test_moderate_short_degree_3(self) -> None:
        """Moderate height + short wavelength -> degree 3."""
        r = classify_douglas_swell(3.0, wavelength_m=50.0)
        assert r is not None
        assert r.degree == 3

    def test_moderate_average_degree_4(self) -> None:
        """Moderate height + average wavelength -> degree 4."""
        r = classify_douglas_swell(3.0, wavelength_m=150.0)
        assert r is not None
        assert r.degree == 4

    def test_moderate_long_degree_5(self) -> None:
        """Moderate height + long wavelength -> degree 5."""
        r = classify_douglas_swell(3.0, wavelength_m=250.0)
        assert r is not None
        assert r.degree == 5

    # ---- Height > 4m (high), varying wavelength ---- #

    def test_high_short_degree_6(self) -> None:
        """High height + short wavelength -> degree 6."""
        r = classify_douglas_swell(5.0, wavelength_m=50.0)
        assert r is not None
        assert r.degree == 6

    def test_high_average_degree_7(self) -> None:
        """High height + average wavelength -> degree 7."""
        r = classify_douglas_swell(5.0, wavelength_m=150.0)
        assert r is not None
        assert r.degree == 7

    def test_high_long_degree_8(self) -> None:
        """High height + long wavelength -> degree 8."""
        r = classify_douglas_swell(5.0, wavelength_m=250.0)
        assert r is not None
        assert r.degree == 8

    # ---- Wavelength boundary tests ---- #

    def test_wavelength_at_100_is_average(self) -> None:
        """Wavelength exactly 100m is average (not short)."""
        r = classify_douglas_swell(3.0, wavelength_m=100.0)
        assert r is not None
        assert r.degree == 4  # moderate + average

    def test_wavelength_at_200_is_average(self) -> None:
        """Wavelength exactly 200m is average (not long)."""
        r = classify_douglas_swell(3.0, wavelength_m=200.0)
        assert r is not None
        assert r.degree == 4  # moderate + average

    def test_wavelength_just_below_100_is_short(self) -> None:
        r = classify_douglas_swell(3.0, wavelength_m=99.9)
        assert r is not None
        assert r.degree == 3  # moderate + short

    def test_wavelength_just_above_200_is_long(self) -> None:
        r = classify_douglas_swell(3.0, wavelength_m=200.1)
        assert r is not None
        assert r.degree == 5  # moderate + long

    # ---- Height boundary tests ---- #

    def test_height_just_below_2_is_low(self) -> None:
        r = classify_douglas_swell(1.99, wavelength_m=150.0)
        assert r is not None
        assert r.degree == 1  # low + average

    def test_height_at_2_is_moderate(self) -> None:
        r = classify_douglas_swell(2.0, wavelength_m=150.0)
        assert r is not None
        assert r.degree == 4  # moderate + average

    def test_height_at_4_is_moderate(self) -> None:
        r = classify_douglas_swell(4.0, wavelength_m=150.0)
        assert r is not None
        assert r.degree == 4  # moderate + average

    def test_height_just_above_4_is_high(self) -> None:
        r = classify_douglas_swell(4.01, wavelength_m=150.0)
        assert r is not None
        assert r.degree == 7  # high + average

    # ---- Period-to-wavelength derivation ---- #

    def test_period_derives_wavelength(self) -> None:
        """Period of 10 s -> wavelength ≈ 156.13 m (average class)."""
        g = 9.80665
        expected_wl = (g / (2 * math.pi)) * 10.0 * 10.0
        r = classify_douglas_swell(3.0, period_s=10.0)
        assert r is not None
        assert r.wavelength_m is not None
        assert abs(r.wavelength_m - expected_wl) < 0.01
        assert r.degree == 4  # moderate + average

    def test_period_short_wavelength(self) -> None:
        """Period of 5 s -> wavelength ≈ 39.0 m (short class)."""
        r = classify_douglas_swell(3.0, period_s=5.0)
        assert r is not None
        assert r.wavelength_m is not None
        assert r.wavelength_m < 100  # short
        assert r.degree == 3  # moderate + short

    def test_period_long_wavelength(self) -> None:
        """Period of 15 s -> wavelength ≈ 351.3 m (long class)."""
        r = classify_douglas_swell(3.0, period_s=15.0)
        assert r is not None
        assert r.wavelength_m is not None
        assert r.wavelength_m > 200  # long
        assert r.degree == 5  # moderate + long

    def test_explicit_wavelength_overrides_period(self) -> None:
        """If both wavelength and period are given, wavelength takes precedence."""
        r = classify_douglas_swell(3.0, wavelength_m=50.0, period_s=15.0)
        assert r is not None
        # 50m is short -> degree 3, not long from 15s period
        assert r.degree == 3
        assert r.wavelength_m == 50.0  # explicit value kept

    def test_zero_period_no_wavelength_derivation(self) -> None:
        """Period of 0 should not derive wavelength (guard against 0)."""
        r = classify_douglas_swell(3.0, period_s=0.0)
        assert r is not None
        # No wavelength derivable, falls back to average
        assert r.wavelength_m is None

    def test_negative_period_no_wavelength_derivation(self) -> None:
        """Negative period should not derive wavelength."""
        r = classify_douglas_swell(3.0, period_s=-5.0)
        assert r is not None
        assert r.wavelength_m is None

    # ---- Missing wavelength fallback ---- #

    def test_no_wavelength_no_period_defaults_average(self) -> None:
        """Without wavelength or period, defaults to 'average' length class."""
        r = classify_douglas_swell(3.0)  # moderate + average default
        assert r is not None
        assert r.degree == 4
        assert r.wavelength_m is None

    def test_low_no_wavelength_degree_1(self) -> None:
        r = classify_douglas_swell(1.0)  # low + average default
        assert r is not None
        assert r.degree == 1

    def test_high_no_wavelength_degree_7(self) -> None:
        r = classify_douglas_swell(5.0)  # high + average default
        assert r is not None
        assert r.degree == 7

    # ---- Result dataclass ---- #

    def test_result_carries_fields(self) -> None:
        r = classify_douglas_swell(3.0, wavelength_m=150.0)
        assert r is not None
        assert r.height_m == 3.0
        assert r.wavelength_m == 150.0

    def test_result_is_frozen(self) -> None:
        r = classify_douglas_swell(3.0, wavelength_m=150.0)
        assert r is not None
        with pytest.raises(AttributeError):
            r.degree = 99  # type: ignore[misc]

    # ---- Full height × wavelength matrix parametrized ---- #

    @pytest.mark.parametrize(
        "height, wavelength, expected_degree",
        [
            # Low height
            (0.5, 50.0, 1),    # low + short
            (0.5, 100.0, 1),   # low + average
            (0.5, 150.0, 1),   # low + average
            (0.5, 200.0, 1),   # low + average
            (0.5, 250.0, 2),   # low + long
            # Moderate height
            (2.5, 50.0, 3),    # moderate + short
            (2.5, 100.0, 4),   # moderate + average
            (2.5, 150.0, 4),   # moderate + average
            (2.5, 200.0, 4),   # moderate + average
            (2.5, 250.0, 5),   # moderate + long
            # High height
            (5.0, 50.0, 6),    # high + short
            (5.0, 100.0, 7),   # high + average
            (5.0, 150.0, 7),   # high + average
            (5.0, 200.0, 7),   # high + average
            (5.0, 250.0, 8),   # high + long
        ],
    )
    def test_height_wavelength_matrix(
        self, height: float, wavelength: float, expected_degree: int
    ) -> None:
        r = classify_douglas_swell(height, wavelength_m=wavelength)
        assert r is not None
        assert r.degree == expected_degree, (
            f"h={height}, wl={wavelength} -> expected {expected_degree}, got {r.degree}"
        )


# --------------------------------------------------------------------------- #
# Beaufort wind force scale                                                    #
# --------------------------------------------------------------------------- #


class TestBeaufort:
    """Beaufort wind force classification from true wind speed."""

    # ---- None / invalid inputs ---- #

    def test_none_returns_none(self) -> None:
        assert classify_beaufort(None) is None

    def test_negative_returns_none(self) -> None:
        assert classify_beaufort(-1.0) is None

    # ---- Force 0: ≤ 0.2 m/s ---- #

    def test_force_0_calm(self) -> None:
        r = classify_beaufort(0.0)
        assert r is not None
        assert r.force == 0
        assert r.label == "Calm"

    def test_force_0_at_boundary(self) -> None:
        r = classify_beaufort(0.2)
        assert r is not None
        assert r.force == 0

    # ---- Force 1: > 0.2 and ≤ 1.5 m/s ---- #

    def test_force_1_light_air(self) -> None:
        r = classify_beaufort(1.0)
        assert r is not None
        assert r.force == 1
        assert r.label == "Light air"

    def test_force_1_at_boundary(self) -> None:
        r = classify_beaufort(1.5)
        assert r is not None
        assert r.force == 1

    # ---- Force 2: > 1.5 and ≤ 3.3 m/s ---- #

    def test_force_2(self) -> None:
        r = classify_beaufort(2.5)
        assert r is not None
        assert r.force == 2
        assert r.label == "Light breeze"

    def test_force_2_at_boundary(self) -> None:
        r = classify_beaufort(3.3)
        assert r is not None
        assert r.force == 2

    # ---- Force 3: > 3.3 and ≤ 5.4 m/s ---- #

    def test_force_3(self) -> None:
        r = classify_beaufort(4.5)
        assert r is not None
        assert r.force == 3
        assert r.label == "Gentle breeze"

    def test_force_3_at_boundary(self) -> None:
        r = classify_beaufort(5.4)
        assert r is not None
        assert r.force == 3

    # ---- Force 4: > 5.4 and ≤ 7.9 m/s ---- #

    def test_force_4(self) -> None:
        r = classify_beaufort(7.0)
        assert r is not None
        assert r.force == 4
        assert r.label == "Moderate breeze"

    def test_force_4_at_boundary(self) -> None:
        r = classify_beaufort(7.9)
        assert r is not None
        assert r.force == 4

    # ---- Force 5: > 7.9 and ≤ 10.7 m/s ---- #

    def test_force_5(self) -> None:
        r = classify_beaufort(9.5)
        assert r is not None
        assert r.force == 5
        assert r.label == "Fresh breeze"

    def test_force_5_at_boundary(self) -> None:
        r = classify_beaufort(10.7)
        assert r is not None
        assert r.force == 5

    # ---- Force 6: > 10.7 and ≤ 13.8 m/s ---- #

    def test_force_6(self) -> None:
        r = classify_beaufort(12.0)
        assert r is not None
        assert r.force == 6
        assert r.label == "Strong breeze"

    def test_force_6_at_boundary(self) -> None:
        r = classify_beaufort(13.8)
        assert r is not None
        assert r.force == 6

    # ---- Force 7: > 13.8 and ≤ 17.1 m/s ---- #

    def test_force_7(self) -> None:
        r = classify_beaufort(15.0)
        assert r is not None
        assert r.force == 7
        assert r.label == "Near gale"

    def test_force_7_at_boundary(self) -> None:
        r = classify_beaufort(17.1)
        assert r is not None
        assert r.force == 7

    # ---- Force 8: > 17.1 and ≤ 20.7 m/s ---- #

    def test_force_8(self) -> None:
        r = classify_beaufort(19.0)
        assert r is not None
        assert r.force == 8
        assert r.label == "Gale"

    def test_force_8_at_boundary(self) -> None:
        r = classify_beaufort(20.7)
        assert r is not None
        assert r.force == 8

    # ---- Force 9: > 20.7 and ≤ 24.4 m/s ---- #

    def test_force_9(self) -> None:
        r = classify_beaufort(22.0)
        assert r is not None
        assert r.force == 9
        assert r.label == "Strong gale"

    def test_force_9_at_boundary(self) -> None:
        r = classify_beaufort(24.4)
        assert r is not None
        assert r.force == 9

    # ---- Force 10: > 24.4 and ≤ 28.4 m/s ---- #

    def test_force_10(self) -> None:
        r = classify_beaufort(26.0)
        assert r is not None
        assert r.force == 10
        assert r.label == "Storm"

    def test_force_10_at_boundary(self) -> None:
        r = classify_beaufort(28.4)
        assert r is not None
        assert r.force == 10

    # ---- Force 11: > 28.4 and ≤ 32.6 m/s ---- #

    def test_force_11(self) -> None:
        r = classify_beaufort(30.0)
        assert r is not None
        assert r.force == 11
        assert r.label == "Violent storm"

    def test_force_11_at_boundary(self) -> None:
        r = classify_beaufort(32.6)
        assert r is not None
        assert r.force == 11

    # ---- Force 12: > 32.6 m/s ---- #

    def test_force_12_hurricane(self) -> None:
        r = classify_beaufort(32.7)
        assert r is not None
        assert r.force == 12
        assert r.label == "Hurricane force"

    def test_force_12_extreme(self) -> None:
        r = classify_beaufort(60.0)
        assert r is not None
        assert r.force == 12

    # ---- Result carries input ---- #

    def test_result_carries_wind_speed(self) -> None:
        r = classify_beaufort(5.5)
        assert r is not None
        assert r.wind_speed_ms == 5.5

    # ---- Frozen dataclass ---- #

    def test_result_is_frozen(self) -> None:
        r = classify_beaufort(5.0)
        assert r is not None
        with pytest.raises(AttributeError):
            r.force = 99  # type: ignore[misc]

    # ---- Parametrized sweep across all boundaries ---- #

    @pytest.mark.parametrize(
        "speed, expected_force",
        [
            (0.0, 0),
            (0.2, 0),
            (0.3, 1),
            (1.5, 1),
            (1.6, 2),
            (3.3, 2),
            (3.4, 3),
            (5.4, 3),
            (5.5, 4),
            (7.9, 4),
            (8.0, 5),
            (10.7, 5),
            (10.8, 6),
            (13.8, 6),
            (13.9, 7),
            (17.1, 7),
            (17.2, 8),
            (20.7, 8),
            (20.8, 9),
            (24.4, 9),
            (24.5, 10),
            (28.4, 10),
            (28.5, 11),
            (32.6, 11),
            (32.7, 12),
            (100.0, 12),
        ],
    )
    def test_boundary_sweep(self, speed: float, expected_force: int) -> None:
        r = classify_beaufort(speed)
        assert r is not None
        assert r.force == expected_force, (
            f"speed={speed} -> expected force {expected_force}, got {r.force}"
        )


# --------------------------------------------------------------------------- #
# Convenience functions                                                        #
# --------------------------------------------------------------------------- #


class TestConvenienceFunctions:
    """Test shorthand helpers that return just degree/force/label."""

    # ---- Douglas degree ---- #

    def test_douglas_degree_none(self) -> None:
        assert douglas_degree_from_hs(None) is None

    def test_douglas_degree_negative(self) -> None:
        assert douglas_degree_from_hs(-1.0) is None

    def test_douglas_degree_moderate(self) -> None:
        assert douglas_degree_from_hs(2.0) == 4

    def test_douglas_degree_zero(self) -> None:
        assert douglas_degree_from_hs(0.0) == 0

    # ---- Douglas label ---- #

    def test_douglas_label_none(self) -> None:
        assert douglas_label_from_hs(None) is None

    def test_douglas_label_moderate(self) -> None:
        assert douglas_label_from_hs(2.0) == "Moderate"

    def test_douglas_label_phenomenal(self) -> None:
        assert douglas_label_from_hs(15.0) == "Phenomenal"

    # ---- Beaufort force ---- #

    def test_beaufort_force_none(self) -> None:
        assert beaufort_force_from_wind(None) is None

    def test_beaufort_force_negative(self) -> None:
        assert beaufort_force_from_wind(-1.0) is None

    def test_beaufort_force_fresh(self) -> None:
        assert beaufort_force_from_wind(9.0) == 5

    def test_beaufort_force_hurricane(self) -> None:
        assert beaufort_force_from_wind(40.0) == 12

    # ---- Beaufort label ---- #

    def test_beaufort_label_none(self) -> None:
        assert beaufort_label_from_wind(None) is None

    def test_beaufort_label_calm(self) -> None:
        assert beaufort_label_from_wind(0.1) == "Calm"

    def test_beaufort_label_strong_breeze(self) -> None:
        assert beaufort_label_from_wind(12.0) == "Strong breeze"


# --------------------------------------------------------------------------- #
# Integration: publisher includes new fields                                   #
# --------------------------------------------------------------------------- #


class TestPublisherIntegration:
    """Verify the publisher outputs Douglas/Beaufort fields correctly."""

    def test_douglas_sea_state_in_values(self) -> None:
        me = _make_estimate(douglas_sea_state=4, douglas_sea_state_label="Moderate")
        values = _motion_estimate_to_values(me)
        by_path = {v["path"]: v["value"] for v in values}
        assert by_path[WAVE_DOUGLAS_SEA_STATE] == 4
        assert by_path[WAVE_DOUGLAS_SEA_STATE_LABEL] == "Moderate"

    def test_douglas_swell_in_values(self) -> None:
        me = _make_estimate(
            douglas_swell=5,
            douglas_swell_label="Moderate rough (long and moderate wave)",
        )
        values = _motion_estimate_to_values(me)
        by_path = {v["path"]: v["value"] for v in values}
        assert by_path[WAVE_DOUGLAS_SWELL] == 5
        assert by_path[WAVE_DOUGLAS_SWELL_LABEL] == "Moderate rough (long and moderate wave)"

    def test_beaufort_in_values(self) -> None:
        me = _make_estimate(beaufort_force=6, beaufort_label="Strong breeze")
        values = _motion_estimate_to_values(me)
        by_path = {v["path"]: v["value"] for v in values}
        assert by_path[WAVE_BEAUFORT_FORCE] == 6
        assert by_path[WAVE_BEAUFORT_LABEL] == "Strong breeze"

    def test_none_fields_omitted(self) -> None:
        """When scale fields are None, they should not appear in output."""
        me = _make_estimate(
            douglas_sea_state=None,
            douglas_sea_state_label=None,
            douglas_swell=None,
            douglas_swell_label=None,
            beaufort_force=None,
            beaufort_label=None,
        )
        values = _motion_estimate_to_values(me)
        paths = {v["path"] for v in values}
        assert WAVE_DOUGLAS_SEA_STATE not in paths
        assert WAVE_DOUGLAS_SEA_STATE_LABEL not in paths
        assert WAVE_DOUGLAS_SWELL not in paths
        assert WAVE_DOUGLAS_SWELL_LABEL not in paths
        assert WAVE_BEAUFORT_FORCE not in paths
        assert WAVE_BEAUFORT_LABEL not in paths

    def test_all_scale_fields_in_delta_message(self) -> None:
        """All three classifications appear in a complete delta message."""
        me = _make_estimate(
            douglas_sea_state=5,
            douglas_sea_state_label="Rough",
            douglas_swell=3,
            douglas_swell_label="Light (short and moderate wave)",
            beaufort_force=7,
            beaufort_label="Near gale",
        )
        msg = build_delta_message(me)
        assert msg is not None
        parsed = json.loads(msg)
        values = parsed["updates"][0]["values"]
        by_path = {v["path"]: v["value"] for v in values}
        assert by_path[WAVE_DOUGLAS_SEA_STATE] == 5
        assert by_path[WAVE_DOUGLAS_SEA_STATE_LABEL] == "Rough"
        assert by_path[WAVE_DOUGLAS_SWELL] == 3
        assert by_path[WAVE_DOUGLAS_SWELL_LABEL] == "Light (short and moderate wave)"
        assert by_path[WAVE_BEAUFORT_FORCE] == 7
        assert by_path[WAVE_BEAUFORT_LABEL] == "Near gale"


# --------------------------------------------------------------------------- #
# Integration: recorder includes new fields                                    #
# --------------------------------------------------------------------------- #


class TestRecorderIntegration:
    """Verify the recorder event dict includes Douglas/Beaufort fields."""

    def test_scale_fields_in_event(self) -> None:
        me = _make_estimate(
            douglas_sea_state=4,
            douglas_sea_state_label="Moderate",
            douglas_swell=2,
            douglas_swell_label="Low (long and low wave)",
            beaufort_force=5,
            beaufort_label="Fresh breeze",
        )
        event = _motion_estimate_to_event(me)
        assert event["douglas_sea_state"] == 4
        assert event["douglas_sea_state_label"] == "Moderate"
        assert event["douglas_swell"] == 2
        assert event["douglas_swell_label"] == "Low (long and low wave)"
        assert event["beaufort_force"] == 5
        assert event["beaufort_label"] == "Fresh breeze"

    def test_none_fields_stripped(self) -> None:
        """None scale fields should be stripped from event dict."""
        me = _make_estimate()
        event = _motion_estimate_to_event(me)
        assert "douglas_sea_state" not in event
        assert "douglas_sea_state_label" not in event
        assert "douglas_swell" not in event
        assert "douglas_swell_label" not in event
        assert "beaufort_force" not in event
        assert "beaufort_label" not in event


# --------------------------------------------------------------------------- #
# Integration: metadata covers all new publish paths                           #
# --------------------------------------------------------------------------- #


class TestMetadataIntegration:
    """Verify WAVE_PATH_META has entries for all new scale paths."""

    def test_douglas_sea_state_path_in_publish_paths(self) -> None:
        assert WAVE_DOUGLAS_SEA_STATE in PUBLISH_PATHS
        assert WAVE_DOUGLAS_SEA_STATE_LABEL in PUBLISH_PATHS

    def test_douglas_swell_path_in_publish_paths(self) -> None:
        assert WAVE_DOUGLAS_SWELL in PUBLISH_PATHS
        assert WAVE_DOUGLAS_SWELL_LABEL in PUBLISH_PATHS

    def test_beaufort_path_in_publish_paths(self) -> None:
        assert WAVE_BEAUFORT_FORCE in PUBLISH_PATHS
        assert WAVE_BEAUFORT_LABEL in PUBLISH_PATHS

    def test_douglas_sea_state_has_metadata(self) -> None:
        assert WAVE_DOUGLAS_SEA_STATE in WAVE_PATH_META
        meta = WAVE_PATH_META[WAVE_DOUGLAS_SEA_STATE]
        assert "description" in meta
        assert "displayName" in meta
        assert "displayScale" in meta
        assert "enum" in meta

    def test_douglas_sea_state_label_has_metadata(self) -> None:
        assert WAVE_DOUGLAS_SEA_STATE_LABEL in WAVE_PATH_META
        meta = WAVE_PATH_META[WAVE_DOUGLAS_SEA_STATE_LABEL]
        assert "description" in meta
        assert "displayName" in meta

    def test_douglas_swell_has_metadata(self) -> None:
        assert WAVE_DOUGLAS_SWELL in WAVE_PATH_META
        meta = WAVE_PATH_META[WAVE_DOUGLAS_SWELL]
        assert "description" in meta
        assert "displayName" in meta
        assert "displayScale" in meta
        assert "enum" in meta

    def test_douglas_swell_label_has_metadata(self) -> None:
        assert WAVE_DOUGLAS_SWELL_LABEL in WAVE_PATH_META
        meta = WAVE_PATH_META[WAVE_DOUGLAS_SWELL_LABEL]
        assert "description" in meta

    def test_beaufort_force_has_metadata(self) -> None:
        assert WAVE_BEAUFORT_FORCE in WAVE_PATH_META
        meta = WAVE_PATH_META[WAVE_BEAUFORT_FORCE]
        assert "description" in meta
        assert "displayName" in meta
        assert "displayScale" in meta

    def test_beaufort_label_has_metadata(self) -> None:
        assert WAVE_BEAUFORT_LABEL in WAVE_PATH_META
        meta = WAVE_PATH_META[WAVE_BEAUFORT_LABEL]
        assert "description" in meta

    def test_douglas_sea_state_enum_has_10_entries(self) -> None:
        """Douglas sea-state enum should have 10 entries (degrees 0-9)."""
        meta = WAVE_PATH_META[WAVE_DOUGLAS_SEA_STATE]
        assert len(meta["enum"]) == 10  # type: ignore[arg-type]

    def test_douglas_swell_enum_has_10_entries(self) -> None:
        """Douglas swell enum should have 10 entries (degrees 0-9)."""
        meta = WAVE_PATH_META[WAVE_DOUGLAS_SWELL]
        assert len(meta["enum"]) == 10  # type: ignore[arg-type]
