/// Standard meteorological and oceanographic scale classifications.
///
/// Mirrors `src/scales.py` exactly.

use std::f64::consts::PI;

const GRAVITY: f64 = 9.80665;

// --------------------------------------------------------------------------- //
// Douglas sea-state scale — wind-sea (WMO Code 3700)                           //
// --------------------------------------------------------------------------- //

const DOUGLAS_WIND_SEA: &[(f64, u8, &str)] = &[
    (0.00, 0, "Calm (glassy)"),
    (0.10, 1, "Calm (rippled)"),
    (0.50, 2, "Smooth"),
    (1.25, 3, "Slight"),
    (2.50, 4, "Moderate"),
    (4.00, 5, "Rough"),
    (6.00, 6, "Very rough"),
    (9.00, 7, "High"),
    (14.00, 8, "Very high"),
];

const SWELL_LABELS: &[(u8, &str)] = &[
    (0, "No swell"),
    (1, "Very low (short/average and low wave)"),
    (2, "Low (long and low wave)"),
    (3, "Light (short and moderate wave)"),
    (4, "Moderate (average and moderate wave)"),
    (5, "Moderate rough (long and moderate wave)"),
    (6, "Rough (short and high wave)"),
    (7, "High (average and high wave)"),
    (8, "Very high (long and high wave)"),
    (9, "Confused"),
];

fn swell_label(degree: u8) -> &'static str {
    SWELL_LABELS
        .iter()
        .find(|(d, _)| *d == degree)
        .map(|(_, l)| *l)
        .unwrap_or("Unknown")
}

// --------------------------------------------------------------------------- //
// Beaufort wind force scale                                                     //
// --------------------------------------------------------------------------- //

const BEAUFORT_UPPER_MS: &[(f64, u8, &str)] = &[
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
];

// --------------------------------------------------------------------------- //
// Result types                                                                  //
// --------------------------------------------------------------------------- //

#[derive(Debug, Clone)]
pub struct DouglasSeaState {
    pub degree: u8,
    pub label: String,
    pub hs_m: f64,
}

#[derive(Debug, Clone)]
pub struct DouglasSwellState {
    pub degree: u8,
    pub label: String,
    pub height_m: Option<f64>,
    pub wavelength_m: Option<f64>,
}

#[derive(Debug, Clone)]
pub struct BeaufortForce {
    pub force: u8,
    pub label: String,
    pub wind_speed_ms: f64,
}

// --------------------------------------------------------------------------- //
// Classification functions                                                      //
// --------------------------------------------------------------------------- //

/// Classify Hs into Douglas sea-state degree (0-9).
pub fn classify_douglas_sea_state(hs_m: Option<f64>) -> Option<DouglasSeaState> {
    let hs = hs_m?;
    if hs < 0.0 {
        return None;
    }
    if hs == 0.0 {
        return Some(DouglasSeaState {
            degree: 0,
            label: "Calm (glassy)".to_string(),
            hs_m: 0.0,
        });
    }

    for &(upper, degree, label) in DOUGLAS_WIND_SEA {
        if degree == 0 {
            continue;
        }
        if hs <= upper {
            return Some(DouglasSeaState {
                degree,
                label: label.to_string(),
                hs_m: hs,
            });
        }
    }

    Some(DouglasSeaState {
        degree: 9,
        label: "Phenomenal".to_string(),
        hs_m: hs,
    })
}

/// Classify swell into Douglas swell degree (0-9).
pub fn classify_douglas_swell(
    height_m: Option<f64>,
    wavelength_m: Option<f64>,
    period_s: Option<f64>,
) -> Option<DouglasSwellState> {
    let height = height_m?;
    if height < 0.0 {
        return None;
    }
    if height == 0.0 {
        return Some(DouglasSwellState {
            degree: 0,
            label: "No swell".to_string(),
            height_m: Some(0.0),
            wavelength_m,
        });
    }

    // Derive wavelength from period if needed
    let wl = wavelength_m.or_else(|| {
        period_s.filter(|&p| p > 0.0).map(|p| GRAVITY / (2.0 * PI) * p * p)
    });

    // Height classes
    let height_class = if height < 2.0 {
        "low"
    } else if height <= 4.0 {
        "moderate"
    } else {
        "high"
    };

    // Wavelength classes
    let length_class = match wl {
        None => "average",
        Some(l) if l < 100.0 => "short",
        Some(l) if l <= 200.0 => "average",
        Some(_) => "long",
    };

    let degree = match (height_class, length_class) {
        ("low", "short") | ("low", "average") => 1,
        ("low", "long") => 2,
        ("moderate", "short") => 3,
        ("moderate", "average") => 4,
        ("moderate", "long") => 5,
        ("high", "short") => 6,
        ("high", "average") => 7,
        ("high", "long") => 8,
        _ => 4,
    };

    Some(DouglasSwellState {
        degree,
        label: swell_label(degree).to_string(),
        height_m: Some(height),
        wavelength_m: wl,
    })
}

/// Classify wind speed into Beaufort force (0-12).
pub fn classify_beaufort(wind_speed_ms: Option<f64>) -> Option<BeaufortForce> {
    let ws = wind_speed_ms?;
    if ws < 0.0 {
        return None;
    }

    for &(upper, force, label) in BEAUFORT_UPPER_MS {
        if ws <= upper {
            return Some(BeaufortForce {
                force,
                label: label.to_string(),
                wind_speed_ms: ws,
            });
        }
    }

    Some(BeaufortForce {
        force: 12,
        label: "Hurricane force".to_string(),
        wind_speed_ms: ws,
    })
}

// Convenience functions
pub fn douglas_degree_from_hs(hs_m: Option<f64>) -> Option<u8> {
    classify_douglas_sea_state(hs_m).map(|r| r.degree)
}

pub fn douglas_label_from_hs(hs_m: Option<f64>) -> Option<String> {
    classify_douglas_sea_state(hs_m).map(|r| r.label)
}

pub fn beaufort_force_from_wind(ws: Option<f64>) -> Option<u8> {
    classify_beaufort(ws).map(|r| r.force)
}

pub fn beaufort_label_from_wind(ws: Option<f64>) -> Option<String> {
    classify_beaufort(ws).map(|r| r.label)
}

// --------------------------------------------------------------------------- //
// Tests                                                                         //
// --------------------------------------------------------------------------- //

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_douglas_sea_state_calm() {
        let r = classify_douglas_sea_state(Some(0.0)).unwrap();
        assert_eq!(r.degree, 0);
    }

    #[test]
    fn test_douglas_sea_state_moderate() {
        let r = classify_douglas_sea_state(Some(2.0)).unwrap();
        assert_eq!(r.degree, 4);
    }

    #[test]
    fn test_douglas_sea_state_phenomenal() {
        let r = classify_douglas_sea_state(Some(15.0)).unwrap();
        assert_eq!(r.degree, 9);
    }

    #[test]
    fn test_douglas_sea_state_none() {
        assert!(classify_douglas_sea_state(None).is_none());
        assert!(classify_douglas_sea_state(Some(-1.0)).is_none());
    }

    #[test]
    fn test_douglas_swell_no_swell() {
        let r = classify_douglas_swell(Some(0.0), None, None).unwrap();
        assert_eq!(r.degree, 0);
    }

    #[test]
    fn test_douglas_swell_with_period() {
        // 1m height, 10s period -> wavelength ≈ 156m (average)
        let r = classify_douglas_swell(Some(1.0), None, Some(10.0)).unwrap();
        assert_eq!(r.degree, 1); // low, average -> 1
    }

    #[test]
    fn test_beaufort_calm() {
        let r = classify_beaufort(Some(0.1)).unwrap();
        assert_eq!(r.force, 0);
    }

    #[test]
    fn test_beaufort_hurricane() {
        let r = classify_beaufort(Some(40.0)).unwrap();
        assert_eq!(r.force, 12);
    }

    #[test]
    fn test_beaufort_none() {
        assert!(classify_beaufort(None).is_none());
    }
}
