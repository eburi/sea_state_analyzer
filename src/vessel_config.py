"""Vessel design data fetcher and hull parameter computation.

Fetches vessel design dimensions from the Signal K REST API and derives
physics parameters used to improve wave estimation accuracy:

- Hull type classification (catamaran / trimaran / monohull) from beam/length ratio
- Resonant wavelength and period from hull length
- Natural roll period range from hull type
- Beam resonant period

These parameters feed into Phase 2 (RAO corrections, hull-aware severity
thresholds) and Phase 3 (online learning of vessel transfer function).

All lengths in metres, periods in seconds, angles in radians.
"""
from __future__ import annotations

import enum
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

GRAVITY = 9.80665  # m/s^2
TWO_PI = 2.0 * math.pi


# --------------------------------------------------------------------------- #
# Hull type classification                                                     #
# --------------------------------------------------------------------------- #

class HullType(enum.Enum):
    """Hull type inferred from beam-to-length ratio."""
    MONOHULL = "monohull"
    TRIMARAN = "trimaran"
    CATAMARAN = "catamaran"
    UNKNOWN = "unknown"


def classify_hull_type(beam_length_ratio: float) -> HullType:
    """Classify hull type from beam-to-length ratio.

    Thresholds based on typical marine architecture:
    - Monohull: ratio < 0.30 (beam ~ 25-30% of LOA)
    - Trimaran: 0.30 <= ratio < 0.40 (wider with amas)
    - Catamaran: ratio >= 0.40 (beam ~ 40-60% of LOA)

    Parameters
    ----------
    beam_length_ratio : float
        Beam / LOA ratio (dimensionless).

    Returns
    -------
    HullType enum value.
    """
    if beam_length_ratio < 0.0:
        return HullType.UNKNOWN
    if beam_length_ratio < 0.30:
        return HullType.MONOHULL
    if beam_length_ratio < 0.40:
        return HullType.TRIMARAN
    return HullType.CATAMARAN


# --------------------------------------------------------------------------- #
# Data structures                                                              #
# --------------------------------------------------------------------------- #

@dataclass
class VesselDesign:
    """Raw vessel design values from Signal K.

    Fields are Optional because the Signal K server may not have all
    design data populated.
    """
    loa: Optional[float] = None             # metres (length overall)
    beam: Optional[float] = None            # metres
    draft_max: Optional[float] = None       # metres
    draft_min: Optional[float] = None       # metres
    air_height: Optional[float] = None      # metres (mast height above waterline)
    displacement: Optional[float] = None    # kg
    ais_ship_type_id: Optional[int] = None  # AIS type code
    ais_ship_type_name: Optional[str] = None  # e.g. "Sailing"
    hull_type_name: Optional[str] = None    # from design.hullType if available
    rigging_name: Optional[str] = None      # from design.rigging if available

    @property
    def beam_length_ratio(self) -> Optional[float]:
        """Beam / LOA ratio (dimensionless)."""
        if self.loa and self.beam and self.loa > 0:
            return self.beam / self.loa
        return None

    @property
    def has_minimum_data(self) -> bool:
        """True if we have enough data to compute hull parameters."""
        return self.loa is not None and self.loa > 0


@dataclass
class HullParameters:
    """Derived physics parameters from vessel design dimensions.

    Used by the feature extractor to apply hull-aware corrections to
    severity scoring, RAO gain, and confidence estimation.
    """
    hull_type: HullType = HullType.UNKNOWN
    beam_length_ratio: Optional[float] = None

    # Hull resonance
    resonant_wavelength: Optional[float] = None    # metres (~ LOA)
    resonant_period: Optional[float] = None        # seconds (deep-water T for resonant_wavelength)

    # Beam resonance
    beam_resonant_wavelength: Optional[float] = None  # metres (~ beam)
    beam_resonant_period: Optional[float] = None      # seconds

    # Natural roll period range (hull-type dependent)
    natural_roll_period_min: Optional[float] = None   # seconds
    natural_roll_period_max: Optional[float] = None   # seconds

    # Natural pitch period range
    natural_pitch_period_min: Optional[float] = None  # seconds
    natural_pitch_period_max: Optional[float] = None  # seconds

    # Raw design data (preserved for logging / debugging)
    design: Optional[VesselDesign] = None

    # Severity weight overrides for this hull type
    # (populated by compute_hull_parameters, consumed by Phase 2)
    severity_weights: Optional[Dict[str, float]] = None
    severity_max_overrides: Optional[Dict[str, float]] = None


# --------------------------------------------------------------------------- #
# Deep-water wave physics                                                      #
# --------------------------------------------------------------------------- #

def wavelength_to_period(wavelength_m: float) -> float:
    """Convert wavelength to period using deep-water dispersion.

    T = sqrt(2 * pi * L / g)

    Parameters
    ----------
    wavelength_m : float
        Wavelength in metres.

    Returns
    -------
    Period in seconds.
    """
    if wavelength_m <= 0:
        raise ValueError(f"wavelength must be positive, got {wavelength_m}")
    return math.sqrt(TWO_PI * wavelength_m / GRAVITY)


def period_to_wavelength(period_s: float) -> float:
    """Convert period to wavelength using deep-water dispersion.

    L = g * T^2 / (2 * pi)

    Parameters
    ----------
    period_s : float
        Period in seconds.

    Returns
    -------
    Wavelength in metres.
    """
    if period_s <= 0:
        raise ValueError(f"period must be positive, got {period_s}")
    return GRAVITY * period_s ** 2 / TWO_PI


# --------------------------------------------------------------------------- #
# Hull parameter computation                                                   #
# --------------------------------------------------------------------------- #

def _natural_roll_period_range(hull_type: HullType) -> Tuple[float, float]:
    """Estimated natural roll period range by hull type.

    These are literature/experience-based ranges:
    - Catamaran: 2-4s (high transverse stiffness, snappy roll)
    - Trimaran: 3-6s (moderate stiffness)
    - Monohull: 5-12s (depends on GM, displacement, beam)

    Returns (min_period, max_period) in seconds.
    """
    if hull_type == HullType.CATAMARAN:
        return (2.0, 4.0)
    elif hull_type == HullType.TRIMARAN:
        return (3.0, 6.0)
    elif hull_type == HullType.MONOHULL:
        return (5.0, 12.0)
    else:
        # Unknown — wide range
        return (2.0, 12.0)


def _natural_pitch_period_range(hull_type: HullType) -> Tuple[float, float]:
    """Estimated natural pitch period range by hull type.

    Pitch period is generally shorter than roll period.
    - Catamaran: 2-4s (similar to roll for cats)
    - Trimaran: 2-5s
    - Monohull: 3-7s

    Returns (min_period, max_period) in seconds.
    """
    if hull_type == HullType.CATAMARAN:
        return (2.0, 4.0)
    elif hull_type == HullType.TRIMARAN:
        return (2.0, 5.0)
    elif hull_type == HullType.MONOHULL:
        return (3.0, 7.0)
    else:
        return (2.0, 7.0)


def _hull_type_severity_weights(hull_type: HullType) -> Dict[str, float]:
    """Suggested severity component weights per hull type.

    Catamarans pitch more relative to roll (high roll stiffness).
    Monohulls roll more relative to pitch.

    Returns a dict compatible with Config.severity_weights.
    """
    if hull_type == HullType.CATAMARAN:
        return {
            "roll_rms": 0.25,
            "pitch_rms": 0.35,
            "roll_spectral": 0.20,
            "yaw_rate_var": 0.20,
        }
    elif hull_type == HullType.TRIMARAN:
        return {
            "roll_rms": 0.30,
            "pitch_rms": 0.30,
            "roll_spectral": 0.25,
            "yaw_rate_var": 0.15,
        }
    else:
        # Monohull or unknown — keep defaults
        return {
            "roll_rms": 0.35,
            "pitch_rms": 0.25,
            "roll_spectral": 0.25,
            "yaw_rate_var": 0.15,
        }


def _hull_type_severity_max(hull_type: HullType) -> Dict[str, float]:
    """Suggested severity normalization max values per hull type.

    Catamarans have much less roll (high transverse stiffness), so
    the roll_rms_max should be lower to maintain sensitivity.
    They also have a shallower draft = less damping = jerkier.

    Returns dict with keys matching Config severity_*_max fields.
    """
    if hull_type == HullType.CATAMARAN:
        return {
            "severity_roll_rms_max": 0.15,       # ~8.6 deg (vs 20 deg for monohull)
            "severity_pitch_rms_max": 0.175,      # same — cats pitch similarly
            "severity_roll_spectral_max": 0.05,   # lower spectral energy expected
            "severity_yaw_rate_var_max": 0.008,   # cats yaw less under wave forcing
        }
    elif hull_type == HullType.TRIMARAN:
        return {
            "severity_roll_rms_max": 0.20,
            "severity_pitch_rms_max": 0.175,
            "severity_roll_spectral_max": 0.07,
            "severity_yaw_rate_var_max": 0.009,
        }
    else:
        # Monohull or unknown — keep defaults
        return {
            "severity_roll_rms_max": 0.35,
            "severity_pitch_rms_max": 0.175,
            "severity_roll_spectral_max": 0.10,
            "severity_yaw_rate_var_max": 0.01,
        }


def compute_hull_parameters(design: VesselDesign) -> HullParameters:
    """Derive hull physics parameters from raw vessel design data.

    Parameters
    ----------
    design : VesselDesign
        Raw design values from Signal K.

    Returns
    -------
    HullParameters with computed physics values.
    """
    params = HullParameters(design=design)

    # Beam-to-length ratio and hull type classification
    bl_ratio = design.beam_length_ratio
    if bl_ratio is not None:
        params.beam_length_ratio = round(bl_ratio, 4)
        params.hull_type = classify_hull_type(bl_ratio)
    elif design.hull_type_name:
        # Fallback: use explicit hull type string from Signal K
        name = design.hull_type_name.lower()
        if "catamaran" in name or "cat" in name:
            params.hull_type = HullType.CATAMARAN
        elif "trimaran" in name or "tri" in name:
            params.hull_type = HullType.TRIMARAN
        elif "mono" in name:
            params.hull_type = HullType.MONOHULL

    # Hull resonance (wavelength ~ LOA)
    if design.loa and design.loa > 0:
        params.resonant_wavelength = design.loa
        params.resonant_period = round(wavelength_to_period(design.loa), 3)

    # Beam resonance (wavelength ~ beam)
    if design.beam and design.beam > 0:
        params.beam_resonant_wavelength = design.beam
        params.beam_resonant_period = round(wavelength_to_period(design.beam), 3)

    # Natural period ranges
    roll_min, roll_max = _natural_roll_period_range(params.hull_type)
    params.natural_roll_period_min = roll_min
    params.natural_roll_period_max = roll_max

    pitch_min, pitch_max = _natural_pitch_period_range(params.hull_type)
    params.natural_pitch_period_min = pitch_min
    params.natural_pitch_period_max = pitch_max

    # Hull-type-specific severity tuning
    params.severity_weights = _hull_type_severity_weights(params.hull_type)
    params.severity_max_overrides = _hull_type_severity_max(params.hull_type)

    return params


# --------------------------------------------------------------------------- #
# Signal K REST API fetch                                                      #
# --------------------------------------------------------------------------- #

def _parse_design_response(data: Dict[str, Any]) -> VesselDesign:
    """Parse the Signal K /design endpoint JSON into a VesselDesign.

    Handles nested structures like:
      {"length": {"value": {"overall": 13.99}}}
      {"beam": {"value": 7.96}}
      {"draft": {"value": {"maximum": 1.35, "minimum": 0.8}}}
      {"aisShipType": {"value": {"id": 36, "name": "Sailing"}}}
      {"airHeight": {"value": 23.21}}
      {"displacement": {"value": 12000}}
      {"hullType": {"value": "catamaran"}}
      {"rigging": {"value": "Sloop"}}

    Gracefully returns partial data if fields are missing.
    """
    design = VesselDesign()

    def _get_value(key: str) -> Any:
        """Extract the 'value' from a Signal K data node."""
        node = data.get(key)
        if isinstance(node, dict):
            return node.get("value")
        return node

    # Length overall
    length_val = _get_value("length")
    if isinstance(length_val, dict):
        design.loa = length_val.get("overall")
        if design.loa is None:
            # Try "hull" or "waterline" as fallback
            design.loa = length_val.get("hull") or length_val.get("waterline")
    elif isinstance(length_val, (int, float)):
        design.loa = float(length_val)

    # Beam
    beam_val = _get_value("beam")
    if isinstance(beam_val, (int, float)):
        design.beam = float(beam_val)

    # Draft
    draft_val = _get_value("draft")
    if isinstance(draft_val, dict):
        design.draft_max = draft_val.get("maximum")
        design.draft_min = draft_val.get("minimum")
    elif isinstance(draft_val, (int, float)):
        design.draft_max = float(draft_val)

    # Air height
    air_val = _get_value("airHeight")
    if isinstance(air_val, (int, float)):
        design.air_height = float(air_val)

    # Displacement
    disp_val = _get_value("displacement")
    if isinstance(disp_val, (int, float)):
        design.displacement = float(disp_val)

    # AIS ship type
    ais_val = _get_value("aisShipType")
    if isinstance(ais_val, dict):
        design.ais_ship_type_id = ais_val.get("id")
        design.ais_ship_type_name = ais_val.get("name")
    elif isinstance(ais_val, (int, float)):
        design.ais_ship_type_id = int(ais_val)

    # Hull type (explicit)
    hull_val = _get_value("hullType")
    if isinstance(hull_val, str):
        design.hull_type_name = hull_val

    # Rigging
    rig_val = _get_value("rigging")
    if isinstance(rig_val, str):
        design.rigging_name = rig_val

    return design


async def fetch_vessel_design(
    base_url: str,
    auth_token: Optional[str] = None,
    timeout_s: float = 10.0,
) -> Optional[VesselDesign]:
    """Fetch vessel design data from Signal K REST API.

    GET {base_url}/signalk/v1/api/vessels/self/design

    Parameters
    ----------
    base_url : str
        Signal K server base URL (e.g. "http://primrose.local:3000").
    auth_token : str, optional
        JWT bearer token for authenticated access.
    timeout_s : float
        HTTP request timeout in seconds.

    Returns
    -------
    VesselDesign or None if the fetch fails or no data is available.
    """
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not installed — cannot fetch vessel design data")
        return None

    url = f"{base_url}/signalk/v1/api/vessels/self/design"
    headers: Dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                logger.warning("Vessel design data not available (404)")
                return None
            if resp.status_code != 200:
                logger.warning(
                    "Failed to fetch vessel design: HTTP %d", resp.status_code
                )
                return None
            data = resp.json()
            if not isinstance(data, dict):
                logger.warning("Unexpected design response type: %s", type(data))
                return None
            design = _parse_design_response(data)
            logger.info(
                "Fetched vessel design: LOA=%.2fm, beam=%.2fm, draft=%.2fm, "
                "ais=%s, hull_type=%s",
                design.loa or 0,
                design.beam or 0,
                design.draft_max or 0,
                design.ais_ship_type_name or "unknown",
                design.hull_type_name or "not set",
            )
            return design
    except Exception as exc:
        logger.warning("Error fetching vessel design: %s", exc)
        return None


def log_hull_parameters(params: HullParameters) -> None:
    """Log computed hull parameters at INFO level."""
    logger.info(
        "Hull parameters: type=%s, B/L=%.3f, resonant_L=%.1fm (T=%.2fs), "
        "beam_resonant_L=%.1fm (T=%.2fs), roll_period=%.1f-%.1fs, "
        "pitch_period=%.1f-%.1fs",
        params.hull_type.value,
        params.beam_length_ratio or 0,
        params.resonant_wavelength or 0,
        params.resonant_period or 0,
        params.beam_resonant_wavelength or 0,
        params.beam_resonant_period or 0,
        params.natural_roll_period_min or 0,
        params.natural_roll_period_max or 0,
        params.natural_pitch_period_min or 0,
        params.natural_pitch_period_max or 0,
    )
    if params.severity_weights:
        logger.info(
            "Hull-type severity weights: %s",
            ", ".join(f"{k}={v:.2f}" for k, v in params.severity_weights.items()),
        )
    if params.severity_max_overrides:
        logger.info(
            "Hull-type severity max overrides: %s",
            ", ".join(f"{k}={v:.4f}" for k, v in params.severity_max_overrides.items()),
        )


# --------------------------------------------------------------------------- #
# RAO gain curve                                                               #
# --------------------------------------------------------------------------- #

def rao_gain(
    wave_period_s: float,
    hull_params: HullParameters,
) -> float:
    """Compute a simplified RAO (Response Amplitude Operator) gain factor.

    Returns how much the hull amplifies (>1) or attenuates (<1) wave motion
    at the given wave period.  Used to correct measured Hs: if the measured
    motion is amplified by hull resonance, the *actual* sea state Hs is
    lower than what naive estimation would report.

    The correction factor is applied as:
        Hs_corrected = Hs_measured / rao_gain

    Model:
    - Near resonant period (wavelength ~ LOA): gain peaks at ~1.5-2.0
    - Near beam resonant period: secondary peak at ~1.3-1.5 (beam seas)
    - Long waves (T >> resonant_T): gain → 1.0 (hull follows wave surface)
    - Very short waves (T << resonant_T): gain < 1.0 (waves too short to
      excite the hull; motion is averaged out)

    The gain curve is a Lorentzian (resonance) shape:
        gain = 1 + (peak - 1) / (1 + ((T - T_res) / bandwidth)^2)

    Parameters
    ----------
    wave_period_s : float
        Wave period in seconds.
    hull_params : HullParameters
        Derived hull physics parameters.

    Returns
    -------
    RAO gain factor (dimensionless, always > 0).
    """
    if wave_period_s <= 0:
        return 1.0

    gain = 1.0

    # Primary resonance: wavelength ~ LOA
    if hull_params.resonant_period is not None and hull_params.resonant_period > 0:
        t_res = hull_params.resonant_period

        # Hull-type-dependent peak gain and bandwidth
        # Conservative values: the RAO model is approximate and uncalibrated.
        # The Phase 3 online learner will refine these over time.
        if hull_params.hull_type == HullType.CATAMARAN:
            peak = 1.25   # conservative until learner calibrates
            bw = 0.8      # moderate bandwidth
        elif hull_params.hull_type == HullType.TRIMARAN:
            peak = 1.20
            bw = 0.9
        else:
            peak = 1.15   # monohull: broader, lower peak
            bw = 1.0

        # Lorentzian resonance curve
        delta = (wave_period_s - t_res) / bw
        gain += (peak - 1.0) / (1.0 + delta * delta)

    # Secondary resonance: beam resonance (mainly affects beam seas)
    if hull_params.beam_resonant_period is not None and hull_params.beam_resonant_period > 0:
        t_beam = hull_params.beam_resonant_period

        if hull_params.hull_type == HullType.CATAMARAN:
            beam_peak = 1.15  # conservative
            beam_bw = 0.6
        else:
            beam_peak = 1.10
            beam_bw = 0.7

        delta_beam = (wave_period_s - t_beam) / beam_bw
        gain += (beam_peak - 1.0) / (1.0 + delta_beam * delta_beam)

    # Short-wave attenuation: waves much shorter than hull can't excite it
    if hull_params.resonant_period is not None and hull_params.resonant_period > 0:
        ratio = wave_period_s / hull_params.resonant_period
        if ratio < 0.3:
            # Progressive attenuation below 30% of resonant period
            gain *= max(0.3, ratio / 0.3)

    return max(0.1, gain)  # floor at 0.1 to avoid division by near-zero


def rao_confidence_adjustment(
    wave_period_s: float,
    hull_params: HullParameters,
) -> Tuple[float, float]:
    """Compute confidence adjustments for wave estimates near resonance.

    Returns (period_conf_boost, hs_conf_penalty):
    - period_conf_boost: multiplier > 1 if period is near natural period
      (strong hull response = clear spectral peak → higher period confidence)
    - hs_conf_penalty: multiplier < 1 if period is near resonance
      (amplified motion = biased Hs estimate → lower Hs confidence)

    Parameters
    ----------
    wave_period_s : float
        Wave period in seconds.
    hull_params : HullParameters
        Derived hull physics parameters.

    Returns
    -------
    (period_conf_boost, hs_conf_penalty) — both in [0.5, 1.5].
    """
    period_boost = 1.0
    hs_penalty = 1.0

    if wave_period_s <= 0:
        return period_boost, hs_penalty

    # Check if period falls within natural roll period range
    roll_min = hull_params.natural_roll_period_min or 2.0
    roll_max = hull_params.natural_roll_period_max or 12.0

    if roll_min <= wave_period_s <= roll_max:
        # Within natural period range: strong response expected
        # Period confidence goes UP (clear signal), Hs confidence goes DOWN (biased)
        # How centred within the range? 1.0 = dead centre
        midpoint = (roll_min + roll_max) / 2.0
        half_range = (roll_max - roll_min) / 2.0
        if half_range > 0:
            centrality = 1.0 - abs(wave_period_s - midpoint) / half_range
        else:
            centrality = 1.0

        period_boost = 1.0 + 0.3 * centrality   # up to 1.3x
        hs_penalty = 1.0 - 0.3 * centrality     # down to 0.7x

    # Additional RAO-based penalty: higher gain = less reliable Hs
    gain = rao_gain(wave_period_s, hull_params)
    if gain > 1.2:
        # Excess gain above 1.2 penalises Hs confidence
        excess = min(1.0, (gain - 1.2) / 1.0)  # normalised 0-1
        hs_penalty *= (1.0 - 0.3 * excess)      # additional up to 30% penalty

    return (
        float(max(0.5, min(1.5, period_boost))),
        float(max(0.5, min(1.5, hs_penalty))),
    )
