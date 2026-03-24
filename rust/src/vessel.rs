/// Vessel hull parameters and RAO gain computation.
///
/// Mirrors the computational parts of `src/vessel_config.py`.
/// REST API fetching stays in Python — only physics computations here.

use std::f64::consts::PI;

const GRAVITY: f64 = 9.80665;
const TWO_PI: f64 = 2.0 * PI;

// --------------------------------------------------------------------------- //
// Hull type                                                                     //
// --------------------------------------------------------------------------- //

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HullType {
    Monohull,
    Trimaran,
    Catamaran,
    Unknown,
}

impl HullType {
    pub fn as_str(&self) -> &'static str {
        match self {
            HullType::Monohull => "monohull",
            HullType::Trimaran => "trimaran",
            HullType::Catamaran => "catamaran",
            HullType::Unknown => "unknown",
        }
    }

    pub fn from_str(s: &str) -> Self {
        let lower = s.to_lowercase();
        if lower.contains("catamaran") || lower.contains("cat") {
            HullType::Catamaran
        } else if lower.contains("trimaran") || lower.contains("tri") {
            HullType::Trimaran
        } else if lower.contains("mono") {
            HullType::Monohull
        } else {
            HullType::Unknown
        }
    }
}

/// Classify hull type from beam-to-length ratio.
pub fn classify_hull_type(beam_length_ratio: f64) -> HullType {
    if beam_length_ratio < 0.0 {
        HullType::Unknown
    } else if beam_length_ratio < 0.30 {
        HullType::Monohull
    } else if beam_length_ratio < 0.40 {
        HullType::Trimaran
    } else {
        HullType::Catamaran
    }
}

// --------------------------------------------------------------------------- //
// Hull parameters                                                               //
// --------------------------------------------------------------------------- //

#[derive(Debug, Clone)]
pub struct HullParameters {
    pub hull_type: HullType,
    pub beam_length_ratio: Option<f64>,
    pub resonant_wavelength: Option<f64>,
    pub resonant_period: Option<f64>,
    pub beam_resonant_wavelength: Option<f64>,
    pub beam_resonant_period: Option<f64>,
    pub natural_roll_period_min: Option<f64>,
    pub natural_roll_period_max: Option<f64>,
    pub natural_pitch_period_min: Option<f64>,
    pub natural_pitch_period_max: Option<f64>,
    pub severity_weights: Option<Vec<(String, f64)>>,
    pub severity_max_overrides: Option<Vec<(String, f64)>>,
}

impl Default for HullParameters {
    fn default() -> Self {
        Self {
            hull_type: HullType::Unknown,
            beam_length_ratio: None,
            resonant_wavelength: None,
            resonant_period: None,
            beam_resonant_wavelength: None,
            beam_resonant_period: None,
            natural_roll_period_min: None,
            natural_roll_period_max: None,
            natural_pitch_period_min: None,
            natural_pitch_period_max: None,
            severity_weights: None,
            severity_max_overrides: None,
        }
    }
}

// --------------------------------------------------------------------------- //
// Deep-water wave physics                                                       //
// --------------------------------------------------------------------------- //

/// Convert wavelength to period: T = sqrt(2π * L / g)
pub fn wavelength_to_period(wavelength_m: f64) -> f64 {
    assert!(wavelength_m > 0.0, "wavelength must be positive");
    (TWO_PI * wavelength_m / GRAVITY).sqrt()
}

/// Convert period to wavelength: L = g * T² / (2π)
pub fn period_to_wavelength(period_s: f64) -> f64 {
    assert!(period_s > 0.0, "period must be positive");
    GRAVITY * period_s * period_s / TWO_PI
}

// --------------------------------------------------------------------------- //
// Natural period ranges                                                         //
// --------------------------------------------------------------------------- //

fn natural_roll_period_range(ht: HullType) -> (f64, f64) {
    match ht {
        HullType::Catamaran => (2.0, 4.0),
        HullType::Trimaran => (3.0, 6.0),
        HullType::Monohull => (5.0, 12.0),
        HullType::Unknown => (2.0, 12.0),
    }
}

fn natural_pitch_period_range(ht: HullType) -> (f64, f64) {
    match ht {
        HullType::Catamaran => (2.0, 4.0),
        HullType::Trimaran => (2.0, 5.0),
        HullType::Monohull => (3.0, 7.0),
        HullType::Unknown => (2.0, 7.0),
    }
}

fn hull_type_severity_weights(ht: HullType) -> Vec<(String, f64)> {
    match ht {
        HullType::Catamaran => vec![
            ("roll_rms".into(), 0.25),
            ("pitch_rms".into(), 0.35),
            ("roll_spectral".into(), 0.20),
            ("yaw_rate_var".into(), 0.20),
        ],
        HullType::Trimaran => vec![
            ("roll_rms".into(), 0.30),
            ("pitch_rms".into(), 0.30),
            ("roll_spectral".into(), 0.25),
            ("yaw_rate_var".into(), 0.15),
        ],
        _ => vec![
            ("roll_rms".into(), 0.35),
            ("pitch_rms".into(), 0.25),
            ("roll_spectral".into(), 0.25),
            ("yaw_rate_var".into(), 0.15),
        ],
    }
}

fn hull_type_severity_max(ht: HullType) -> Vec<(String, f64)> {
    match ht {
        HullType::Catamaran => vec![
            ("severity_roll_rms_max".into(), 0.15),
            ("severity_pitch_rms_max".into(), 0.175),
            ("severity_roll_spectral_max".into(), 0.05),
            ("severity_yaw_rate_var_max".into(), 0.008),
        ],
        HullType::Trimaran => vec![
            ("severity_roll_rms_max".into(), 0.20),
            ("severity_pitch_rms_max".into(), 0.175),
            ("severity_roll_spectral_max".into(), 0.07),
            ("severity_yaw_rate_var_max".into(), 0.009),
        ],
        _ => vec![
            ("severity_roll_rms_max".into(), 0.35),
            ("severity_pitch_rms_max".into(), 0.175),
            ("severity_roll_spectral_max".into(), 0.10),
            ("severity_yaw_rate_var_max".into(), 0.01),
        ],
    }
}

/// Compute hull parameters from LOA, beam, and optional hull type name.
pub fn compute_hull_parameters(
    loa: Option<f64>,
    beam: Option<f64>,
    hull_type_name: Option<&str>,
) -> HullParameters {
    let mut params = HullParameters::default();

    // Beam-to-length ratio and hull type
    let bl_ratio = match (loa, beam) {
        (Some(l), Some(b)) if l > 0.0 => Some(b / l),
        _ => None,
    };

    if let Some(ratio) = bl_ratio {
        params.beam_length_ratio = Some((ratio * 10000.0).round() / 10000.0);
        params.hull_type = classify_hull_type(ratio);
    } else if let Some(name) = hull_type_name {
        params.hull_type = HullType::from_str(name);
    }

    // Hull resonance
    if let Some(l) = loa {
        if l > 0.0 {
            params.resonant_wavelength = Some(l);
            params.resonant_period = Some((wavelength_to_period(l) * 1000.0).round() / 1000.0);
        }
    }

    // Beam resonance
    if let Some(b) = beam {
        if b > 0.0 {
            params.beam_resonant_wavelength = Some(b);
            params.beam_resonant_period = Some((wavelength_to_period(b) * 1000.0).round() / 1000.0);
        }
    }

    // Natural periods
    let (roll_min, roll_max) = natural_roll_period_range(params.hull_type);
    params.natural_roll_period_min = Some(roll_min);
    params.natural_roll_period_max = Some(roll_max);

    let (pitch_min, pitch_max) = natural_pitch_period_range(params.hull_type);
    params.natural_pitch_period_min = Some(pitch_min);
    params.natural_pitch_period_max = Some(pitch_max);

    // Severity tuning
    params.severity_weights = Some(hull_type_severity_weights(params.hull_type));
    params.severity_max_overrides = Some(hull_type_severity_max(params.hull_type));

    params
}

// --------------------------------------------------------------------------- //
// RAO gain curve                                                                //
// --------------------------------------------------------------------------- //

/// Compute RAO gain factor at the given wave period.
///
/// Returns how much the hull amplifies (>1) or attenuates (<1) wave motion.
pub fn rao_gain(wave_period_s: f64, hp: &HullParameters) -> f64 {
    if wave_period_s <= 0.0 {
        return 1.0;
    }

    let mut gain = 1.0;

    // Primary resonance: wavelength ~ LOA
    if let Some(t_res) = hp.resonant_period {
        if t_res > 0.0 {
            let (peak, bw) = match hp.hull_type {
                HullType::Catamaran => (1.25, 0.8),
                HullType::Trimaran => (1.20, 0.9),
                _ => (1.15, 1.0),
            };
            let delta = (wave_period_s - t_res) / bw;
            gain += (peak - 1.0) / (1.0 + delta * delta);
        }
    }

    // Secondary resonance: beam
    if let Some(t_beam) = hp.beam_resonant_period {
        if t_beam > 0.0 {
            let (beam_peak, beam_bw) = match hp.hull_type {
                HullType::Catamaran => (1.15, 0.6),
                _ => (1.10, 0.7),
            };
            let delta_beam = (wave_period_s - t_beam) / beam_bw;
            gain += (beam_peak - 1.0) / (1.0 + delta_beam * delta_beam);
        }
    }

    // Short-wave attenuation
    if let Some(t_res) = hp.resonant_period {
        if t_res > 0.0 {
            let ratio = wave_period_s / t_res;
            if ratio < 0.3 {
                gain *= (ratio / 0.3).max(0.3);
            }
        }
    }

    gain.max(0.1)
}

/// Compute confidence adjustments for wave estimates near resonance.
///
/// Returns (period_conf_boost, hs_conf_penalty).
pub fn rao_confidence_adjustment(
    wave_period_s: f64,
    hp: &HullParameters,
) -> (f64, f64) {
    let mut period_boost = 1.0_f64;
    let mut hs_penalty = 1.0_f64;

    if wave_period_s <= 0.0 {
        return (period_boost, hs_penalty);
    }

    let roll_min = hp.natural_roll_period_min.unwrap_or(2.0);
    let roll_max = hp.natural_roll_period_max.unwrap_or(12.0);

    if roll_min <= wave_period_s && wave_period_s <= roll_max {
        let midpoint = (roll_min + roll_max) / 2.0;
        let half_range = (roll_max - roll_min) / 2.0;
        let centrality = if half_range > 0.0 {
            1.0 - (wave_period_s - midpoint).abs() / half_range
        } else {
            1.0
        };
        period_boost = 1.0 + 0.3 * centrality;
        hs_penalty = 1.0 - 0.3 * centrality;
    }

    // Additional RAO-based penalty
    let gain = rao_gain(wave_period_s, hp);
    if gain > 1.2 {
        let excess = ((gain - 1.2) / 1.0).min(1.0);
        hs_penalty *= 1.0 - 0.3 * excess;
    }

    (
        period_boost.clamp(0.5, 1.5),
        hs_penalty.clamp(0.5, 1.5),
    )
}

// --------------------------------------------------------------------------- //
// Tests                                                                         //
// --------------------------------------------------------------------------- //

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_classify_hull_type() {
        assert_eq!(classify_hull_type(0.25), HullType::Monohull);
        assert_eq!(classify_hull_type(0.35), HullType::Trimaran);
        assert_eq!(classify_hull_type(0.50), HullType::Catamaran);
        assert_eq!(classify_hull_type(-0.1), HullType::Unknown);
    }

    #[test]
    fn test_wavelength_period_roundtrip() {
        let l = 100.0;
        let t = wavelength_to_period(l);
        let l2 = period_to_wavelength(t);
        assert!((l - l2).abs() < 1e-8);
    }

    #[test]
    fn test_compute_hull_parameters() {
        let hp = compute_hull_parameters(Some(13.99), Some(7.96), None);
        assert_eq!(hp.hull_type, HullType::Catamaran); // 7.96/13.99 ≈ 0.569
        assert!(hp.resonant_period.is_some());
        assert!(hp.beam_resonant_period.is_some());
    }

    #[test]
    fn test_rao_gain_at_resonance() {
        let hp = compute_hull_parameters(Some(13.99), Some(7.96), None);
        let t_res = hp.resonant_period.unwrap();
        let gain = rao_gain(t_res, &hp);
        assert!(gain > 1.0, "gain at resonance should be > 1.0, got {}", gain);
    }

    #[test]
    fn test_rao_gain_far_from_resonance() {
        let hp = compute_hull_parameters(Some(13.99), Some(7.96), None);
        let gain = rao_gain(20.0, &hp);
        assert!((gain - 1.0).abs() < 0.2, "gain far from resonance should be ~1.0, got {}", gain);
    }

    #[test]
    fn test_rao_confidence_adjustment() {
        let hp = compute_hull_parameters(Some(13.99), Some(7.96), None);
        // Inside natural roll period range for catamaran (2-4s)
        let (boost, penalty) = rao_confidence_adjustment(3.0, &hp);
        assert!(boost > 1.0);
        assert!(penalty < 1.0);
    }
}
