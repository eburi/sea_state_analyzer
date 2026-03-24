/// Doppler correction: encounter frequency → true wave frequency.
///
/// Mirrors the Doppler functions in `src/feature_extractor.py`.
/// Reference: bareboat-necessities wave estimation math.

use std::f64::consts::PI;

const GRAVITY: f64 = 9.80665;

/// Convert encounter frequency to true wave frequency via Doppler correction.
///
/// Returns `Some((true_period_s, wavelength_m, phase_speed_m_s))` or `None`
/// if correction is infeasible.
pub fn doppler_correct(
    encounter_freq_hz: f64,
    delta_v: f64,
) -> Option<(f64, f64, f64)> {
    if encounter_freq_hz <= 0.0 {
        return None;
    }

    let omega_e = 2.0 * PI * encounter_freq_hz;
    let g = GRAVITY;

    // When delta_v ≈ 0 there is no Doppler shift
    if delta_v.abs() < 0.05 {
        let t = 1.0 / encounter_freq_hz;
        let l = g * t * t / (2.0 * PI);
        let c = g * t / (2.0 * PI);
        return Some((t, l, c));
    }

    // Forward Doppler: (Δv/g)·ω² + ω - ω_e = 0
    let a_coeff = delta_v / g;
    let discriminant = 1.0 + 4.0 * a_coeff * omega_e;

    if discriminant < 0.0 {
        return None;
    }

    let sqrt_disc = discriminant.sqrt();

    // Two roots: ω = (-1 ± √disc) / (2·Δv/g)
    let omega_1 = (-1.0 + sqrt_disc) / (2.0 * a_coeff);
    let omega_2 = (-1.0 - sqrt_disc) / (2.0 * a_coeff);

    // Pick the positive root closest to omega_e
    let mut candidates = Vec::with_capacity(2);
    if omega_1 > 0.0 {
        candidates.push(omega_1);
    }
    if omega_2 > 0.0 {
        candidates.push(omega_2);
    }

    if candidates.is_empty() {
        return None;
    }

    let omega_true = candidates
        .into_iter()
        .min_by(|a, b| {
            (a - omega_e)
                .abs()
                .partial_cmp(&(b - omega_e).abs())
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .unwrap();

    let t = 2.0 * PI / omega_true;
    let l = g * t * t / (2.0 * PI);
    let c = g * t / (2.0 * PI);

    // Sanity: reject non-physical results (1–30 s period)
    if t < 1.0 || t > 30.0 {
        return None;
    }

    Some((t, l, c))
}

/// Estimate delta_v from STW and true wind angle.
///
/// Returns `None` if insufficient data.
pub fn compute_delta_v(
    stw: Option<f64>,
    wind_angle_true: Option<f64>,
) -> Option<f64> {
    let stw = stw?;
    if stw < 0.1 {
        return None;
    }
    let wa = wind_angle_true?;
    Some(stw * wa.cos())
}

/// Classify wave heading from delta_v / STW ratio.
pub fn classify_wave_heading(
    delta_v: Option<f64>,
    stw: Option<f64>,
) -> Option<&'static str> {
    let dv = delta_v?;
    let s = stw?;
    if s < 0.1 {
        return None;
    }
    let ratio = dv / s;

    Some(if ratio > 0.7 {
        "head"
    } else if ratio > 0.3 {
        "quartering_head"
    } else if ratio > -0.3 {
        "beam"
    } else if ratio > -0.7 {
        "quartering_following"
    } else {
        "following"
    })
}

// --------------------------------------------------------------------------- //
// Tests                                                                         //
// --------------------------------------------------------------------------- //

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_doppler_no_speed() {
        // delta_v ≈ 0 → encounter == true
        let result = doppler_correct(0.1, 0.0).unwrap();
        assert!((result.0 - 10.0).abs() < 0.01);
    }

    #[test]
    fn test_doppler_head_seas() {
        // Head seas: delta_v > 0 → true period > encounter period
        let result = doppler_correct(0.2, 2.0);
        assert!(result.is_some());
        let (t, l, c) = result.unwrap();
        assert!(t > 1.0 / 0.2); // True period should be longer
        assert!(l > 0.0);
        assert!(c > 0.0);
    }

    #[test]
    fn test_doppler_negative_discriminant() {
        // Strong following sea that makes the quadratic infeasible
        let result = doppler_correct(0.05, -10.0);
        // Should return None
        assert!(result.is_none());
    }

    #[test]
    fn test_compute_delta_v() {
        // Head wind (angle=0): delta_v = STW * cos(0) = STW
        assert!((compute_delta_v(Some(3.0), Some(0.0)).unwrap() - 3.0).abs() < 1e-10);

        // Beam wind (angle=π/2): delta_v ≈ 0
        let dv = compute_delta_v(Some(3.0), Some(PI / 2.0)).unwrap();
        assert!(dv.abs() < 1e-10);

        // No STW
        assert!(compute_delta_v(None, Some(0.0)).is_none());
        assert!(compute_delta_v(Some(0.05), Some(0.0)).is_none());
    }

    #[test]
    fn test_classify_wave_heading() {
        assert_eq!(classify_wave_heading(Some(3.0), Some(3.0)), Some("head"));
        assert_eq!(classify_wave_heading(Some(-3.0), Some(3.0)), Some("following"));
        assert_eq!(classify_wave_heading(Some(0.0), Some(3.0)), Some("beam"));
        assert!(classify_wave_heading(None, Some(3.0)).is_none());
    }
}
