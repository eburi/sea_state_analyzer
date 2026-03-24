/// Heave and wave estimation from vertical acceleration.
///
/// Mirrors the computational parts of `src/heave_estimator.py`.

use std::collections::VecDeque;
use std::f64::consts::PI;

use crate::dsp;
use crate::vessel::HullParameters;

const GRAVITY: f64 = 9.80665;

#[derive(Debug, Clone)]
pub struct TrochoidalEstimate {
    pub significant_height: f64,
    pub wave_amplitude: f64,
    pub wavelength: f64,
    pub wave_speed: f64,
    pub b_parameter: f64,
    pub accel_max: f64,
    pub frequency_hz: f64,
    pub method: String,
}

pub fn trochoidal_wave_height(
    accel_max_observed: f64,
    frequency_hz: f64,
    delta_v: f64,
    min_amplitude: f64,
) -> Option<TrochoidalEstimate> {
    if !(0.02..=2.0).contains(&frequency_hz) || accel_max_observed <= 0.01 {
        return None;
    }

    let f_o = frequency_hz;
    let g = GRAVITY;
    let mut doppler_applied = false;

    let wavelength = if delta_v.abs() < 0.05 {
        g / (2.0 * PI * f_o * f_o)
    } else {
        let discriminant = 8.0 * PI * f_o * g * delta_v + g * g;
        if discriminant < 0.0 {
            g / (2.0 * PI * f_o * f_o)
        } else {
            let sign_dv = if delta_v >= 0.0 { 1.0 } else { -1.0 };
            doppler_applied = true;
            (sign_dv * discriminant.sqrt() + 4.0 * PI * f_o * delta_v + g)
                / (4.0 * PI * f_o * f_o)
        }
    };

    if wavelength <= 0.5 {
        return None;
    }

    let wave_speed = (g * wavelength / (2.0 * PI)).sqrt();
    let k = 2.0 * PI / wavelength;

    let a_max = if doppler_applied {
        let effective_speed = wave_speed + delta_v;
        if effective_speed.abs() < 0.1 {
            return None;
        }
        accel_max_observed * (wave_speed * wave_speed) / (effective_speed * effective_speed)
    } else {
        accel_max_observed
    };

    let mut ratio = a_max / g;
    if ratio <= 0.0 {
        return None;
    }
    if ratio > 1.0 {
        ratio = 1.0;
    }

    let b = wavelength / (2.0 * PI) * ratio.ln();
    let mut amplitude = (k * b).exp() / k;
    let max_amplitude = wavelength / (2.0 * PI);
    if amplitude > max_amplitude {
        amplitude = max_amplitude;
    }
    if amplitude < min_amplitude {
        return None;
    }

    let method = if doppler_applied || delta_v.abs() < 0.05 {
        "trochoidal"
    } else {
        "trochoidal_no_doppler"
    };

    Some(TrochoidalEstimate {
        significant_height: 2.0 * amplitude,
        wave_amplitude: amplitude,
        wavelength,
        wave_speed,
        b_parameter: b,
        accel_max: a_max,
        frequency_hz,
        method: method.to_string(),
    })
}

#[derive(Debug, Clone)]
pub struct HeaveEstimate {
    pub heave_displacement: f64,
    pub heave_amplitude: f64,
    pub significant_height: f64,
    pub heave_std: f64,
    pub heave_max: f64,
    pub heave_min: f64,
    pub n_samples: usize,
    pub converged: bool,
    pub method: String,
}

#[derive(Debug, Clone)]
pub struct KalmanHeaveEstimator {
    dt: f64,
    accel_bias_window: usize,
    f: [[f64; 3]; 3],
    b: [f64; 3],
    q: [[f64; 3]; 3],
    r: f64,
    x: [f64; 3],
    p: [[f64; 3]; 3],
    accel_buf: VecDeque<f64>,
    accel_bias: f64,
    heave_history: VecDeque<f64>,
    n_processed: usize,
}

impl KalmanHeaveEstimator {
    pub fn new(
        dt: f64,
        pos_integral_trans_var: f64,
        pos_trans_var: f64,
        vel_trans_var: f64,
        pos_integral_obs_var: f64,
        accel_bias_window: usize,
    ) -> Self {
        let dt2 = dt * dt;
        let dt3 = dt2 * dt;
        Self {
            dt,
            accel_bias_window,
            f: [
                [1.0, dt, 0.5 * dt2],
                [0.0, 1.0, dt],
                [0.0, 0.0, 1.0],
            ],
            b: [dt3 / 6.0, 0.5 * dt2, dt],
            q: [
                [pos_integral_trans_var, 0.0, 0.0],
                [0.0, pos_trans_var, 0.0],
                [0.0, 0.0, vel_trans_var],
            ],
            r: pos_integral_obs_var,
            x: [0.0, 0.0, 0.0],
            p: [
                [pos_integral_obs_var, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ],
            accel_buf: VecDeque::with_capacity(accel_bias_window),
            accel_bias: 0.0,
            heave_history: VecDeque::with_capacity((300.0 / dt).max(1.0) as usize),
            n_processed: 0,
        }
    }

    #[allow(dead_code)]
    pub fn default_50hz() -> Self {
        Self::new(0.02, 1e-6, 1e-4, 1e-2, 1e-1, 500)
    }

    pub fn reset(&mut self, initial_displacement: f64, initial_velocity: f64) {
        self.x = [0.0, initial_displacement, initial_velocity];
        self.p = [[self.r, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]];
        self.accel_buf.clear();
        self.accel_bias = 0.0;
        self.heave_history.clear();
        self.n_processed = 0;
    }

    pub fn update(&mut self, vertical_accel: f64) -> f64 {
        if self.accel_buf.len() == self.accel_bias_window {
            self.accel_buf.pop_front();
        }
        self.accel_buf.push_back(vertical_accel);
        if self.accel_buf.len() >= 10 {
            let sum: f64 = self.accel_buf.iter().sum();
            self.accel_bias = sum / self.accel_buf.len() as f64;
        }

        let accel_corrected = vertical_accel - self.accel_bias;
        let x_pred = mat3_vec3_mul(&self.f, &self.x);
        let x_pred = add_vec3(&x_pred, &scale_vec3(&self.b, accel_corrected));

        let p_pred = add_mat3(&mat3_mul(&mat3_mul(&self.f, &self.p), &mat3_transpose(&self.f)), &self.q);

        let s = p_pred[0][0] + self.r;
        let k = [p_pred[0][0] / s, p_pred[1][0] / s, p_pred[2][0] / s];
        let y = -x_pred[0];

        self.x = [
            x_pred[0] + k[0] * y,
            x_pred[1] + k[1] * y,
            x_pred[2] + k[2] * y,
        ];

        let kh = [
            [k[0], 0.0, 0.0],
            [k[1], 0.0, 0.0],
            [k[2], 0.0, 0.0],
        ];
        let i_minus_kh = sub_mat3(&identity3(), &kh);
        self.p = mat3_mul(&i_minus_kh, &p_pred);

        let displacement = self.x[1];
        let max_hist = (300.0 / self.dt).max(1.0) as usize;
        if self.heave_history.len() == max_hist {
            self.heave_history.pop_front();
        }
        self.heave_history.push_back(displacement);
        self.n_processed += 1;
        displacement
    }

    pub fn get_estimate(&self, min_samples: usize) -> Option<HeaveEstimate> {
        if self.heave_history.len() < min_samples {
            return None;
        }

        let arr: Vec<f64> = self.heave_history.iter().copied().collect();
        let heave_std = dsp::std_dev(&arr);
        let heave_max = arr.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        let heave_min = arr.iter().copied().fold(f64::INFINITY, f64::min);
        let converged = self.n_processed >= self.accel_bias_window && self.x[0].abs() < 10.0;

        Some(HeaveEstimate {
            heave_displacement: self.x[1],
            heave_amplitude: (heave_max - heave_min) / 2.0,
            significant_height: 4.0 * heave_std,
            heave_std,
            heave_max,
            heave_min,
            n_samples: self.n_processed,
            converged,
            method: "kalman".to_string(),
        })
    }

    pub fn displacement(&self) -> f64 {
        self.x[1]
    }

    pub fn velocity(&self) -> f64 {
        self.x[2]
    }

    pub fn n_processed(&self) -> usize {
        self.n_processed
    }
}

fn identity3() -> [[f64; 3]; 3] {
    [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
}

fn add_vec3(a: &[f64; 3], b: &[f64; 3]) -> [f64; 3] {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}

fn scale_vec3(a: &[f64; 3], s: f64) -> [f64; 3] {
    [a[0] * s, a[1] * s, a[2] * s]
}

fn mat3_vec3_mul(a: &[[f64; 3]; 3], x: &[f64; 3]) -> [f64; 3] {
    [
        a[0][0] * x[0] + a[0][1] * x[1] + a[0][2] * x[2],
        a[1][0] * x[0] + a[1][1] * x[1] + a[1][2] * x[2],
        a[2][0] * x[0] + a[2][1] * x[1] + a[2][2] * x[2],
    ]
}

fn mat3_transpose(a: &[[f64; 3]; 3]) -> [[f64; 3]; 3] {
    [
        [a[0][0], a[1][0], a[2][0]],
        [a[0][1], a[1][1], a[2][1]],
        [a[0][2], a[1][2], a[2][2]],
    ]
}

fn mat3_mul(a: &[[f64; 3]; 3], b: &[[f64; 3]; 3]) -> [[f64; 3]; 3] {
    let mut out = [[0.0; 3]; 3];
    for i in 0..3 {
        for j in 0..3 {
            out[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j];
        }
    }
    out
}

fn add_mat3(a: &[[f64; 3]; 3], b: &[[f64; 3]; 3]) -> [[f64; 3]; 3] {
    let mut out = [[0.0; 3]; 3];
    for i in 0..3 {
        for j in 0..3 {
            out[i][j] = a[i][j] + b[i][j];
        }
    }
    out
}

fn sub_mat3(a: &[[f64; 3]; 3], b: &[[f64; 3]; 3]) -> [[f64; 3]; 3] {
    let mut out = [[0.0; 3]; 3];
    for i in 0..3 {
        for j in 0..3 {
            out[i][j] = a[i][j] - b[i][j];
        }
    }
    out
}

#[allow(dead_code)]
pub fn butterworth_lowpass(data: &[f64], cutoff_hz: f64, fs: f64) -> Vec<f64> {
    dsp::butterworth_lowpass(data, cutoff_hz, fs)
}

#[allow(dead_code)]
pub fn hull_resonance_suppression(
    freqs: &[f64],
    psd: &[f64],
    hull_params: &HullParameters,
    suppression_factor: f64,
    bandwidth_hz: f64,
) -> Vec<f64> {
    if bandwidth_hz <= 0.0 || freqs.len() != psd.len() {
        return psd.to_vec();
    }

    let mut resonance_freqs = Vec::new();
    if let Some(p) = hull_params.resonant_period {
        if p > 0.0 {
            resonance_freqs.push(1.0 / p);
        }
    }
    if let Some(p) = hull_params.beam_resonant_period {
        if p > 0.0 {
            resonance_freqs.push(1.0 / p);
        }
    }
    for (p_min, p_max) in [
        (
            hull_params.natural_roll_period_min,
            hull_params.natural_roll_period_max,
        ),
        (
            hull_params.natural_pitch_period_min,
            hull_params.natural_pitch_period_max,
        ),
    ] {
        if let (Some(min_p), Some(max_p)) = (p_min, p_max) {
            if min_p > 0.0 && max_p > 0.0 {
                resonance_freqs.push(1.0 / ((min_p + max_p) / 2.0));
            }
        }
    }
    if resonance_freqs.is_empty() {
        return psd.to_vec();
    }

    resonance_freqs.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let mut unique_freqs = Vec::new();
    for f in resonance_freqs {
        if unique_freqs.is_empty() || f - unique_freqs[unique_freqs.len() - 1] > bandwidth_hz {
            unique_freqs.push(f);
        }
    }

    let mut result = psd.to_vec();
    for f_res in unique_freqs {
        for (i, f) in freqs.iter().enumerate() {
            let gaussian = (-0.5 * ((*f - f_res) / bandwidth_hz).powi(2)).exp();
            let multiplier = 1.0 - (1.0 - suppression_factor) * gaussian;
            result[i] *= multiplier;
        }
    }
    result
}

#[allow(dead_code)]
pub fn spectral_hs_from_displacement_psd(
    freqs: &[f64],
    accel_psd: &[f64],
    freq_min_hz: f64,
    freq_max_hz: f64,
) -> Option<f64> {
    let mut f_valid = Vec::new();
    let mut psd_disp = Vec::new();

    for (&f, &p) in freqs.iter().zip(accel_psd.iter()) {
        if f > freq_min_hz && f <= freq_max_hz {
            let omega4 = ((2.0 * PI * f).powi(4)).max(1e-12);
            f_valid.push(f);
            psd_disp.push(p / omega4);
        }
    }

    if f_valid.len() < 2 {
        return None;
    }
    let m0 = trapz(&psd_disp, &f_valid);
    if m0 <= 0.0 {
        return None;
    }
    Some(4.0 * m0.sqrt())
}

#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct WavePartition {
    pub component_type: String,
    pub peak_freq_hz: f64,
    pub peak_period_s: f64,
    pub hs_m: f64,
    pub m0: f64,
    pub freq_min_hz: f64,
    pub freq_max_hz: f64,
    pub confidence: f64,
}

#[allow(dead_code)]
pub fn extract_wave_partitions(
    freqs: &[f64],
    psd_disp: &[f64],
    freq_min_hz: f64,
    freq_max_hz: f64,
    max_peaks: usize,
) -> Vec<WavePartition> {
    let mut f = Vec::new();
    let mut p = Vec::new();
    for (&freq, &power) in freqs.iter().zip(psd_disp.iter()) {
        if freq.is_finite()
            && power.is_finite()
            && freq > freq_min_hz
            && freq <= freq_max_hz
            && power > 0.0
        {
            f.push(freq);
            p.push(power);
        }
    }
    if f.len() < 8 {
        return Vec::new();
    }

    let max_power = p.iter().copied().fold(0.0_f64, f64::max);
    let prominence = max_power * 0.02;
    let distance = (f.len() / 20).max(1);
    let peaks = find_prominent_peaks(&p, prominence, distance);
    if peaks.is_empty() {
        return Vec::new();
    }

    let mut ranked = peaks;
    ranked.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    ranked.truncate(max_peaks);
    let mut peak_idx: Vec<usize> = ranked.into_iter().map(|(idx, _)| idx).collect();
    peak_idx.sort_unstable();
    if peak_idx.is_empty() {
        return Vec::new();
    }

    let mut bounds = Vec::new();
    let mut start = 0usize;
    for pair in peak_idx.windows(2) {
        let left = pair[0];
        let right = pair[1];
        let mut valley_idx = left;
        let mut valley_val = p[left];
        for (offset, &val) in p[left..=right].iter().enumerate() {
            if val < valley_val {
                valley_val = val;
                valley_idx = left + offset;
            }
        }
        bounds.push((start, valley_idx));
        start = valley_idx + 1;
    }
    bounds.push((start, f.len() - 1));

    let mut total_m0 = 0.0;
    let mut raw_parts: Vec<(usize, f64, f64, f64, f64, f64, usize, usize)> = Vec::new();
    for (b_start, b_end) in bounds {
        if b_end <= b_start + 1 {
            continue;
        }
        let f_seg = &f[b_start..=b_end];
        let p_seg = &p[b_start..=b_end];
        let m0 = trapz(p_seg, f_seg);
        if m0 <= 0.0 {
            continue;
        }
        let mut peak_local = 0usize;
        let mut peak_val = p_seg[0];
        for (idx, &val) in p_seg.iter().enumerate() {
            if val > peak_val {
                peak_val = val;
                peak_local = idx;
            }
        }
        let peak_global = b_start + peak_local;
        let peak_freq = f[peak_global];
        let peak_period = if peak_freq > 0.0 { 1.0 / peak_freq } else { 0.0 };
        let hs = 4.0 * m0.sqrt();
        total_m0 += m0;
        raw_parts.push((peak_global, peak_freq, peak_period, hs, m0, peak_val, b_start, b_end));
    }
    if raw_parts.is_empty() || total_m0 <= 0.0 {
        return Vec::new();
    }

    let mut by_freq_desc = raw_parts.clone();
    by_freq_desc.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    let mut labels = std::collections::HashMap::new();
    if !by_freq_desc.is_empty() {
        labels.insert(by_freq_desc[0].0, "wind_wave");
    }
    if by_freq_desc.len() >= 2 {
        labels.insert(by_freq_desc[1].0, "swell_1");
    }
    if by_freq_desc.len() >= 3 {
        labels.insert(by_freq_desc[2].0, "swell_2");
    }

    let p_mean = dsp::mean(&p) + 1e-12;
    let mut out = Vec::new();
    for (peak_global, peak_freq, peak_period, hs, m0, pmax, b_start, b_end) in raw_parts {
        let Some(label) = labels.get(&peak_global) else {
            continue;
        };
        let energy_share = (m0 / total_m0).clamp(0.0, 1.0);
        let sharpness = (pmax / p_mean / 10.0).clamp(0.0, 1.0);
        let confidence = (0.7 * energy_share + 0.3 * sharpness).clamp(0.0, 1.0);
        out.push(WavePartition {
            component_type: (*label).to_string(),
            peak_freq_hz: peak_freq,
            peak_period_s: peak_period,
            hs_m: hs,
            m0,
            freq_min_hz: f[b_start],
            freq_max_hz: f[b_end],
            confidence,
        });
    }
    fn order(label: &str) -> usize {
        match label {
            "wind_wave" => 0,
            "swell_1" => 1,
            "swell_2" => 2,
            _ => 99,
        }
    }
    out.sort_by_key(|w| order(&w.component_type));
    out
}

#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct WaveEstimate {
    pub trochoidal: Option<TrochoidalEstimate>,
    pub kalman: Option<HeaveEstimate>,
    pub significant_height: Option<f64>,
    pub heave: Option<f64>,
    pub confidence: f64,
    pub method_used: Option<String>,
    pub spectral_hs: Option<f64>,
    pub spectral_partitions: Option<Vec<WavePartition>>,
    pub accel_dominant_freq: Option<f64>,
    pub accel_dominant_period: Option<f64>,
    pub accel_freq_confidence: Option<f64>,
    pub accel_rms: Option<f64>,
    pub accel_max: Option<f64>,
}

#[allow(dead_code)]
impl Default for WaveEstimate {
    fn default() -> Self {
        Self {
            trochoidal: None,
            kalman: None,
            significant_height: None,
            heave: None,
            confidence: 0.0,
            method_used: None,
            spectral_hs: None,
            spectral_partitions: None,
            accel_dominant_freq: None,
            accel_dominant_period: None,
            accel_freq_confidence: None,
            accel_rms: None,
            accel_max: None,
        }
    }
}

#[allow(dead_code)]
pub fn estimate_waves_from_accel(
    vertical_accel: &[f64],
    fs: f64,
    delta_v: f64,
    kalman_estimator: Option<&mut KalmanHeaveEstimator>,
    lowpass_cutoff_mult: f64,
    psd_min_samples: usize,
    freq_min_hz: f64,
    freq_max_hz: f64,
    trochoidal_min_amplitude: f64,
    hull_params: Option<&HullParameters>,
) -> WaveEstimate {
    let mut result = WaveEstimate::default();
    if vertical_accel.len() < psd_min_samples {
        return result;
    }

    result.accel_rms = Some(dsp::rms(vertical_accel));

    let nperseg = (vertical_accel.len() / 2).min(2048).max(8);
    let centered: Vec<f64> = {
        let m = dsp::mean(vertical_accel);
        vertical_accel.iter().map(|v| v - m).collect()
    };
    let (freqs, psd) = dsp::welch_psd(&centered, fs, nperseg);
    if psd.is_empty() || psd.iter().sum::<f64>() == 0.0 {
        return result;
    }

    let valid_mask: Vec<bool> = freqs
        .iter()
        .map(|f| *f > freq_min_hz && *f <= freq_max_hz)
        .collect();
    if !valid_mask.iter().any(|v| *v) {
        return result;
    }

    let mut psd_valid = psd.clone();
    for (i, valid) in valid_mask.iter().enumerate() {
        if !valid {
            psd_valid[i] = 0.0;
        }
    }
    let valid_max = psd_valid.iter().copied().fold(0.0_f64, f64::max);
    if valid_max == 0.0 {
        return result;
    }

    result.spectral_hs = spectral_hs_from_displacement_psd(&freqs, &psd_valid, freq_min_hz, freq_max_hz);

    let mut psd_disp = psd_valid.clone();
    for (i, f) in freqs.iter().enumerate() {
        let freq_sq = (*f * *f).max(1e-6);
        psd_disp[i] /= freq_sq;
    }
    if let Some(hp) = hull_params {
        psd_disp = hull_resonance_suppression(&freqs, &psd_disp, hp, 0.1, 0.08);
    }

    let disp_valid_max = psd_disp
        .iter()
        .zip(valid_mask.iter())
        .filter(|(_, valid)| **valid)
        .map(|(p, _)| *p)
        .fold(0.0_f64, f64::max);
    if disp_valid_max == 0.0 {
        return result;
    }

    result.spectral_partitions = Some(extract_wave_partitions(
        &freqs,
        &psd_disp,
        freq_min_hz,
        freq_max_hz,
        3,
    ));

    let idx = argmax(&psd_disp);
    let dom_freq = freqs[idx];
    let peak_power = psd_valid[idx];
    let mean_power = mean_where(&psd_valid, &valid_mask) + 1e-12;
    let confidence = (peak_power / mean_power / 10.0).min(1.0);

    result.accel_dominant_freq = Some(dom_freq);
    result.accel_dominant_period = if dom_freq > 0.0 { Some(1.0 / dom_freq) } else { None };
    result.accel_freq_confidence = Some(confidence);

    let cutoff = dom_freq * lowpass_cutoff_mult;
    let filtered = butterworth_lowpass(vertical_accel, cutoff, fs);
    let accel_max = filtered.iter().map(|v| v.abs()).fold(0.0_f64, f64::max);
    result.accel_max = Some(accel_max);

    result.trochoidal = trochoidal_wave_height(
        accel_max,
        dom_freq,
        delta_v,
        trochoidal_min_amplitude,
    );

    if let Some(estimator) = kalman_estimator {
        for &sample in &filtered {
            estimator.update(sample);
        }
        result.kalman = estimator.get_estimate(100);
    }

    if let (Some(troch), Some(kalman)) = (&result.trochoidal, &result.kalman) {
        if kalman.converged {
            let ratio = kalman.significant_height / (troch.significant_height + 1e-6);
            if ratio > 0.3 && ratio < 3.0 {
                result.significant_height = Some(kalman.significant_height);
                result.heave = Some(kalman.heave_displacement);
                result.method_used = Some("kalman".to_string());
                result.confidence = confidence.min(if kalman.converged { 0.8 } else { 0.4 });
            } else {
                result.significant_height = Some(troch.significant_height);
                result.heave = Some(kalman.heave_displacement);
                result.method_used = Some("trochoidal".to_string());
                result.confidence = confidence * 0.5;
            }
        }
    } else if let Some(troch) = &result.trochoidal {
        result.significant_height = Some(troch.significant_height);
        result.method_used = Some("trochoidal".to_string());
        result.confidence = confidence * 0.6;
    } else if let Some(kalman) = &result.kalman {
        if kalman.converged {
            result.significant_height = Some(kalman.significant_height);
            result.heave = Some(kalman.heave_displacement);
            result.method_used = Some("kalman".to_string());
            result.confidence = 0.4;
        }
    }

    if let Some(spectral_hs) = result.spectral_hs {
        if spectral_hs > 0.05 {
            match result.significant_height {
                None => {
                    result.significant_height = Some(spectral_hs);
                    result.method_used = Some("spectral".to_string());
                    result.confidence = confidence * 0.5;
                }
                Some(current) if current < spectral_hs * 0.4 => {
                    result.significant_height = Some(spectral_hs);
                    result.method_used = Some("spectral".to_string());
                    result.confidence = confidence * 0.5;
                }
                _ => {}
            }
        }
    }

    result
}

#[allow(dead_code)]
fn trapz(y: &[f64], x: &[f64]) -> f64 {
    if y.len() < 2 || x.len() != y.len() {
        return 0.0;
    }
    let mut total = 0.0;
    for i in 0..(y.len() - 1) {
        total += 0.5 * (y[i] + y[i + 1]) * (x[i + 1] - x[i]);
    }
    total
}

#[allow(dead_code)]
fn argmax(values: &[f64]) -> usize {
    let mut idx = 0usize;
    let mut best = f64::NEG_INFINITY;
    for (i, &v) in values.iter().enumerate() {
        if v > best {
            best = v;
            idx = i;
        }
    }
    idx
}

#[allow(dead_code)]
fn mean_where(values: &[f64], mask: &[bool]) -> f64 {
    let mut sum = 0.0;
    let mut count = 0usize;
    for (&v, &keep) in values.iter().zip(mask.iter()) {
        if keep {
            sum += v;
            count += 1;
        }
    }
    if count == 0 {
        0.0
    } else {
        sum / count as f64
    }
}

#[allow(dead_code)]
fn find_prominent_peaks(values: &[f64], prominence: f64, distance: usize) -> Vec<(usize, f64)> {
    if values.len() < 3 {
        return Vec::new();
    }

    let mut peaks = Vec::new();
    for i in 1..(values.len() - 1) {
        if values[i] <= values[i - 1] || values[i] < values[i + 1] {
            continue;
        }

        let mut left_min = values[i];
        let mut j = i;
        while j > 0 {
            j -= 1;
            left_min = left_min.min(values[j]);
            if values[j] > values[i] {
                break;
            }
        }

        let mut right_min = values[i];
        let mut k = i;
        while k + 1 < values.len() {
            k += 1;
            right_min = right_min.min(values[k]);
            if values[k] > values[i] {
                break;
            }
        }

        let prom = values[i] - left_min.max(right_min);
        if prom >= prominence {
            peaks.push((i, prom));
        }
    }

    peaks.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    let mut selected: Vec<(usize, f64)> = Vec::new();
    'outer: for peak in peaks {
        for existing in &selected {
            if peak.0.abs_diff(existing.0) < distance {
                continue 'outer;
            }
        }
        selected.push(peak);
    }
    selected
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_trochoidal_basic() {
        let est = trochoidal_wave_height(0.5, 0.1, 0.0, 0.005).unwrap();
        assert!(est.significant_height > 0.0);
        assert!(est.wavelength > 0.0);
    }

    #[test]
    fn test_kalman_runs() {
        let mut est = KalmanHeaveEstimator::default_50hz();
        for i in 0..500 {
            let t = i as f64 * 0.02;
            let accel = (2.0 * PI * 0.2 * t).sin() * 0.5;
            est.update(accel);
        }
        let out = est.get_estimate(100).unwrap();
        assert!(out.n_samples >= 500);
    }

    #[test]
    fn test_spectral_hs() {
        let freqs = vec![0.0, 0.05, 0.1, 0.2, 0.5];
        let psd = vec![0.0, 0.1, 0.5, 0.2, 0.01];
        let hs = spectral_hs_from_displacement_psd(&freqs, &psd, 0.03, 1.0);
        assert!(hs.is_some());
        assert!(hs.unwrap() > 0.0);
    }
}
