"""Standard meteorological and oceanographic scale classifications.

Douglas sea-state scale (WMO Code 3700):
    Maps significant wave height (Hs) to degree 0-9.
    Separate codes for wind-sea and swell.

Beaufort wind force scale:
    Maps wind speed (m/s) at 10 m reference height to force 0-12.

All inputs follow Signal K conventions:
    Heights  – metres
    Speeds   – m/s
    Periods  – seconds
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


# --------------------------------------------------------------------------- #
# Douglas sea-state scale — wind-sea (WMO Code 3700)                         #
# --------------------------------------------------------------------------- #

# Each entry is (upper_bound_hs_m, degree, label).
# The upper bound is *exclusive* except for degree 9 (unbounded).
_DOUGLAS_WIND_SEA: list[Tuple[float, int, str]] = [
    (0.00, 0, "Calm (glassy)"),
    (0.10, 1, "Calm (rippled)"),
    (0.50, 2, "Smooth"),
    (1.25, 3, "Slight"),
    (2.50, 4, "Moderate"),
    (4.00, 5, "Rough"),
    (6.00, 6, "Very rough"),
    (9.00, 7, "High"),
    (14.00, 8, "Very high"),
    # 9 = Phenomenal (>14 m) — handled as fallthrough
]

# Douglas swell scale — WMO Code 3701
# Combines wavelength (short < 100m, average 100-200m, long > 200m)
# and wave height (low < 2m, moderate 2-4m, high > 4m) into degree 0-9.
#
# Degree:  Length       Height
# 0        -            No swell
# 1        Short/Avg    Low        (< 2m, λ < 200m)
# 2        Long         Low        (< 2m, λ ≥ 200m)
# 3        Short        Moderate   (2-4m, λ < 100m)
# 4        Average      Moderate   (2-4m, 100m ≤ λ < 200m)
# 5        Long         Moderate   (2-4m, λ ≥ 200m)
# 6        Short        High       (> 4m, λ < 100m)
# 7        Average      High       (> 4m, 100m ≤ λ < 200m)
# 8        Long         High       (> 4m, λ ≥ 200m)
# 9        Confused     (indeterminate wavelength and height)

_SWELL_LABELS: dict[int, str] = {
    0: "No swell",
    1: "Very low (short/average and low wave)",
    2: "Low (long and low wave)",
    3: "Light (short and moderate wave)",
    4: "Moderate (average and moderate wave)",
    5: "Moderate rough (long and moderate wave)",
    6: "Rough (short and high wave)",
    7: "High (average and high wave)",
    8: "Very high (long and high wave)",
    9: "Confused",
}


# --------------------------------------------------------------------------- #
# Beaufort wind force scale — WMO standard (force 0-12)                       #
# --------------------------------------------------------------------------- #

# Upper bounds of wind speed in m/s for each Beaufort number.
# Formula: v = 0.836 * B^1.5  (approximate; official thresholds used here)
_BEAUFORT_UPPER_MS: list[Tuple[float, int, str]] = [
    (0.2, 0, "Calm"),
    (1.5, 1, "Light air"),
    (3.3, 2, "Light breeze"),
    (5.4, 3, "Gentle breeze"),
    (7.9, 4, "Moderate breeze"),
    (10.7, 5, "Fresh breeze"),
    (13.8, 6, "Strong breeze"),
    (17.1, 7, "Near gale"),
    (20.7, 8, "Gale"),
    (24.4, 9, "Strong gale"),
    (28.4, 10, "Storm"),
    (32.6, 11, "Violent storm"),
    # 12 = Hurricane force (≥ 32.7 m/s) — handled as fallthrough
]


# --------------------------------------------------------------------------- #
# Result dataclasses                                                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DouglasSeaState:
    """Douglas wind-sea state classification result."""

    degree: int  # 0-9
    label: str  # e.g. "Moderate"
    hs_m: float  # significant wave height used for classification


@dataclass(frozen=True)
class DouglasSwellState:
    """Douglas swell classification result."""

    degree: int  # 0-9
    label: str
    height_m: Optional[float]  # swell height used
    wavelength_m: Optional[float]  # wavelength used (from period via dispersion)


@dataclass(frozen=True)
class BeaufortForce:
    """Beaufort wind force classification result."""

    force: int  # 0-12
    label: str  # e.g. "Strong breeze"
    wind_speed_ms: float  # wind speed used for classification


# --------------------------------------------------------------------------- #
# Classification functions                                                     #
# --------------------------------------------------------------------------- #


def classify_douglas_sea_state(hs_m: Optional[float]) -> Optional[DouglasSeaState]:
    """Classify significant wave height into Douglas sea-state degree (0-9).

    Args:
        hs_m: Significant wave height in metres.  None or negative returns None.

    Returns:
        DouglasSeaState with degree, label, and the height used.
    """
    if hs_m is None or hs_m < 0:
        return None

    # Degree 0: exactly zero (no wave)
    if hs_m == 0.0:
        return DouglasSeaState(degree=0, label="Calm (glassy)", hs_m=0.0)

    for upper, degree, label in _DOUGLAS_WIND_SEA:
        if degree == 0:
            continue  # skip the zero entry, handled above
        if hs_m <= upper:
            return DouglasSeaState(degree=degree, label=label, hs_m=hs_m)

    # > 14 m
    return DouglasSeaState(degree=9, label="Phenomenal", hs_m=hs_m)


def classify_douglas_swell(
    height_m: Optional[float],
    wavelength_m: Optional[float] = None,
    period_s: Optional[float] = None,
) -> Optional[DouglasSwellState]:
    """Classify swell into Douglas swell degree (0-9).

    Uses swell height and wavelength.  If wavelength is not provided but
    period is, wavelength is estimated via deep-water dispersion relation:
        λ = (g / 2π) * T²  ≈ 1.5613 * T²

    Args:
        height_m:     Swell component height in metres.
        wavelength_m: Wavelength in metres (optional).
        period_s:     Swell period in seconds (used if wavelength_m is None).

    Returns:
        DouglasSwellState or None if height is unavailable.
    """
    if height_m is None or height_m < 0:
        return None

    if height_m == 0.0:
        return DouglasSwellState(
            degree=0, label="No swell", height_m=0.0, wavelength_m=wavelength_m
        )

    # Derive wavelength from period if needed
    wl = wavelength_m
    if wl is None and period_s is not None and period_s > 0:
        # Deep-water dispersion: λ = g * T² / (2π)
        import math

        g = 9.80665
        wl = (g / (2 * math.pi)) * period_s * period_s

    # Height classes: low < 2m, moderate 2-4m, high > 4m
    if height_m < 2.0:
        height_class = "low"
    elif height_m <= 4.0:
        height_class = "moderate"
    else:
        height_class = "high"

    # Wavelength classes: short < 100m, average 100-200m, long > 200m
    if wl is None:
        # Without wavelength, best-guess based on height alone
        # Use the middle wavelength class (average) as default
        length_class = "average"
    elif wl < 100:
        length_class = "short"
    elif wl <= 200:
        length_class = "average"
    else:
        length_class = "long"

    # Map to degree
    _SWELL_MATRIX: dict[Tuple[str, str], int] = {
        ("low", "short"): 1,
        ("low", "average"): 1,
        ("low", "long"): 2,
        ("moderate", "short"): 3,
        ("moderate", "average"): 4,
        ("moderate", "long"): 5,
        ("high", "short"): 6,
        ("high", "average"): 7,
        ("high", "long"): 8,
    }

    degree = _SWELL_MATRIX.get((height_class, length_class), 4)
    label = _SWELL_LABELS[degree]

    return DouglasSwellState(
        degree=degree, label=label, height_m=height_m, wavelength_m=wl
    )


def classify_beaufort(wind_speed_ms: Optional[float]) -> Optional[BeaufortForce]:
    """Classify wind speed into Beaufort force (0-12).

    Args:
        wind_speed_ms: True wind speed in m/s.  None or negative returns None.

    Returns:
        BeaufortForce with force number, label, and wind speed used.
    """
    if wind_speed_ms is None or wind_speed_ms < 0:
        return None

    for upper, force, label in _BEAUFORT_UPPER_MS:
        if wind_speed_ms <= upper:
            return BeaufortForce(force=force, label=label, wind_speed_ms=wind_speed_ms)

    # ≥ 32.7 m/s
    return BeaufortForce(force=12, label="Hurricane force", wind_speed_ms=wind_speed_ms)


# --------------------------------------------------------------------------- #
# Convenience: combined classification from MotionEstimate fields             #
# --------------------------------------------------------------------------- #


def douglas_degree_from_hs(hs_m: Optional[float]) -> Optional[int]:
    """Return just the Douglas degree integer (0-9) from Hs, or None."""
    result = classify_douglas_sea_state(hs_m)
    return result.degree if result else None


def douglas_label_from_hs(hs_m: Optional[float]) -> Optional[str]:
    """Return just the Douglas label string from Hs, or None."""
    result = classify_douglas_sea_state(hs_m)
    return result.label if result else None


def beaufort_force_from_wind(wind_speed_ms: Optional[float]) -> Optional[int]:
    """Return just the Beaufort force integer (0-12) from wind speed, or None."""
    result = classify_beaufort(wind_speed_ms)
    return result.force if result else None


def beaufort_label_from_wind(wind_speed_ms: Optional[float]) -> Optional[str]:
    """Return just the Beaufort label string from wind speed, or None."""
    result = classify_beaufort(wind_speed_ms)
    return result.label if result else None
