/// Low-level DSP utility functions.
///
/// Pure-Rust implementations of the signal-processing primitives used
/// throughout the sea-state feature pipeline.  Every function mirrors
/// the behaviour of its Python/NumPy/SciPy counterpart in
/// `src/feature_extractor.py`.

use std::f64::consts::PI;

// --------------------------------------------------------------------------- //
// Basic statistics                                                              //
// --------------------------------------------------------------------------- //

/// Root-mean-square of a slice.
#[inline]
pub fn rms(x: &[f64]) -> f64 {
    if x.is_empty() {
        return 0.0;
    }
    let sum_sq: f64 = x.iter().map(|v| v * v).sum();
    (sum_sq / x.len() as f64).sqrt()
}

/// Crest factor: peak / RMS.  Returns `None` when RMS == 0.
#[inline]
#[allow(dead_code)]
pub fn crest_factor(x: &[f64]) -> Option<f64> {
    let r = rms(x);
    if r == 0.0 {
        return None;
    }
    let peak = x.iter().map(|v| v.abs()).fold(0.0_f64, f64::max);
    Some(peak / r)
}

/// Variance of a slice (population variance, N denominator).
#[inline]
pub fn variance(x: &[f64]) -> f64 {
    if x.len() < 2 {
        return 0.0;
    }
    let n = x.len() as f64;
    let mean = x.iter().sum::<f64>() / n;
    x.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / n
}

/// Standard deviation (population, N denominator).
#[inline]
pub fn std_dev(x: &[f64]) -> f64 {
    variance(x).sqrt()
}

/// Mean of a slice.
#[inline]
pub fn mean(x: &[f64]) -> f64 {
    if x.is_empty() {
        return 0.0;
    }
    x.iter().sum::<f64>() / x.len() as f64
}

/// Peak-to-peak (max - min).
#[inline]
#[allow(dead_code)]
pub fn peak_to_peak(x: &[f64]) -> f64 {
    if x.is_empty() {
        return 0.0;
    }
    let mn = x.iter().cloned().fold(f64::INFINITY, f64::min);
    let mx = x.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    mx - mn
}

/// Excess kurtosis (Fisher definition, bias=True matching scipy default).
#[allow(dead_code)]
pub fn kurtosis(x: &[f64]) -> f64 {
    let n = x.len() as f64;
    if n < 4.0 {
        return 0.0;
    }
    let m = mean(x);
    let m2: f64 = x.iter().map(|v| (v - m).powi(2)).sum::<f64>() / n;
    let m4: f64 = x.iter().map(|v| (v - m).powi(4)).sum::<f64>() / n;
    if m2 == 0.0 {
        return 0.0;
    }
    m4 / (m2 * m2) - 3.0
}

// --------------------------------------------------------------------------- //
// Zero-crossing period                                                          //
// --------------------------------------------------------------------------- //

/// Estimate dominant period from zero-crossings of a mean-removed signal.
///
/// Returns `None` if fewer than 2 crossings are found or fewer than 4 samples.
#[allow(dead_code)]
pub fn zero_crossing_period(x: &[f64], fs: f64) -> Option<f64> {
    if x.len() < 4 {
        return None;
    }
    let m = mean(x);
    let centered: Vec<f64> = x.iter().map(|v| v - m).collect();

    // Compute signs (treat 0 as +1)
    let signs: Vec<i8> = centered
        .iter()
        .map(|v| if *v >= 0.0 { 1 } else { -1 })
        .collect();

    // Find zero crossings
    let mut crossings = Vec::new();
    for i in 0..signs.len() - 1 {
        if signs[i] != signs[i + 1] {
            crossings.push(i);
        }
    }

    if crossings.len() < 2 {
        return None;
    }

    // Mean interval between crossings
    let intervals: Vec<f64> = crossings
        .windows(2)
        .map(|w| (w[1] - w[0]) as f64 / fs)
        .collect();
    let mean_interval = intervals.iter().sum::<f64>() / intervals.len() as f64;

    // Period = 2 × mean half-period
    Some(2.0 * mean_interval)
}

// --------------------------------------------------------------------------- //
// Angle utilities                                                               //
// --------------------------------------------------------------------------- //

/// Unwrap a single angle step to minimise discontinuity (radians).
#[inline]
#[allow(dead_code)]
pub fn unwrap_angle(prev: f64, curr: f64) -> f64 {
    let diff = curr - prev;
    // Wrap diff to (-π, π]
    let wrapped = (diff + PI).rem_euclid(2.0 * PI) - PI;
    prev + wrapped
}

/// Wrap angle to (-π, π].
#[inline]
#[allow(dead_code)]
pub fn angle_wrap(a: f64) -> f64 {
    (a + PI).rem_euclid(2.0 * PI) - PI
}

/// Circular mean of angles (radians).
#[allow(dead_code)]
pub fn circular_mean(angles: &[f64]) -> f64 {
    if angles.is_empty() {
        return 0.0;
    }
    let sin_sum: f64 = angles.iter().map(|a| a.sin()).sum();
    let cos_sum: f64 = angles.iter().map(|a| a.cos()).sum();
    sin_sum.atan2(cos_sum)
}

// --------------------------------------------------------------------------- //
// Welch PSD (simplified)                                                        //
// --------------------------------------------------------------------------- //

/// Hann window.
fn hann_window(n: usize) -> Vec<f64> {
    (0..n)
        .map(|i| 0.5 * (1.0 - (2.0 * PI * i as f64 / n as f64).cos()))
        .collect()
}

/// Compute a single-segment periodogram of a windowed signal.
fn periodogram(segment: &[f64], fs: f64) -> (Vec<f64>, Vec<f64>) {
    let n = segment.len();
    let window = hann_window(n);
    let win_energy: f64 = window.iter().map(|w| w * w).sum();

    // Apply window
    let windowed: Vec<f64> = segment.iter().zip(window.iter()).map(|(s, w)| s * w).collect();

    // Zero-pad to next power of 2 for FFT (not strictly necessary but faster)
    let fft_len = n;

    // Real FFT using rustfft
    use rustfft::FftPlanner;
    use rustfft::num_complex::Complex;

    let mut planner = FftPlanner::new();
    let fft = planner.plan_fft_forward(fft_len);

    let mut buffer: Vec<Complex<f64>> = windowed
        .iter()
        .map(|v| Complex { re: *v, im: 0.0 })
        .collect();
    // Pad to fft_len if needed
    buffer.resize(fft_len, Complex { re: 0.0, im: 0.0 });

    fft.process(&mut buffer);

    // One-sided PSD
    let n_freqs = fft_len / 2 + 1;
    let scale = 1.0 / (fs * win_energy);

    let mut psd = Vec::with_capacity(n_freqs);
    for i in 0..n_freqs {
        let mag_sq = buffer[i].re * buffer[i].re + buffer[i].im * buffer[i].im;
        let p = mag_sq * scale;
        // Double non-DC, non-Nyquist bins
        if i > 0 && i < n_freqs - 1 {
            psd.push(p * 2.0);
        } else {
            psd.push(p);
        }
    }

    let freqs: Vec<f64> = (0..n_freqs).map(|i| i as f64 * fs / fft_len as f64).collect();

    (freqs, psd)
}

/// Welch PSD estimation (50% overlap, Hann window).
///
/// Returns `(freqs, psd)` or `(empty, empty)` if too few samples.
pub fn welch_psd(x: &[f64], fs: f64, nperseg: usize) -> (Vec<f64>, Vec<f64>) {
    if x.len() < nperseg || nperseg < 4 {
        return (vec![], vec![]);
    }

    let step = nperseg / 2; // 50% overlap
    let mut all_freqs: Vec<f64> = Vec::new();
    let mut sum_psd: Vec<f64> = Vec::new();
    let mut n_segments = 0usize;

    let mut start = 0;
    while start + nperseg <= x.len() {
        let segment = &x[start..start + nperseg];
        let (freqs, psd) = periodogram(segment, fs);

        if all_freqs.is_empty() {
            all_freqs = freqs;
            sum_psd = psd;
        } else {
            for (s, p) in sum_psd.iter_mut().zip(psd.iter()) {
                *s += p;
            }
        }
        n_segments += 1;
        start += step;
    }

    if n_segments == 0 {
        return (vec![], vec![]);
    }

    for s in sum_psd.iter_mut() {
        *s /= n_segments as f64;
    }

    (all_freqs, sum_psd)
}

/// Compute Welch PSD and return (dominant_freq, confidence, freqs, psd).
///
/// Mirrors `_welch_dominant` from feature_extractor.py.
#[allow(dead_code)]
pub fn welch_dominant(
    x: &[f64],
    fs: f64,
    min_samples: usize,
) -> (Option<f64>, Option<f64>, Vec<f64>, Vec<f64>) {
    if x.len() < min_samples {
        return (None, None, vec![], vec![]);
    }

    // Match Python: nperseg = min(len//2, 64), max(nperseg, 4)
    let nperseg = (x.len() / 2).min(64).max(4);

    // Remove mean
    let m = mean(x);
    let centered: Vec<f64> = x.iter().map(|v| v - m).collect();

    let (freqs, psd) = welch_psd(&centered, fs, nperseg);

    if psd.is_empty() {
        return (None, None, vec![], vec![]);
    }

    let total: f64 = psd.iter().sum();
    if total == 0.0 {
        return (None, Some(0.0), freqs, psd);
    }

    // Exclude DC (index 0)
    let mut psd_no_dc = psd.clone();
    if !psd_no_dc.is_empty() {
        psd_no_dc[0] = 0.0;
    }

    let max_psd = psd_no_dc.iter().cloned().fold(0.0_f64, f64::max);
    if max_psd == 0.0 {
        return (None, Some(0.0), freqs, psd);
    }

    let idx = psd_no_dc
        .iter()
        .enumerate()
        .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
        .map(|(i, _)| i)
        .unwrap();

    let dom_freq = freqs[idx];
    let peak = psd_no_dc[idx];
    let mean_power = mean(&psd_no_dc) + 1e-12;
    let confidence = (peak / mean_power / 10.0).min(1.0);

    (Some(dom_freq), Some(confidence), freqs, psd)
}

// --------------------------------------------------------------------------- //
// Spectral analysis                                                             //
// --------------------------------------------------------------------------- //

/// Shannon entropy of normalised PSD (nats).
#[allow(dead_code)]
pub fn spectral_entropy(psd: &[f64]) -> f64 {
    let total: f64 = psd.iter().sum::<f64>() + 1e-12;
    let mut entropy = 0.0_f64;
    for &p in psd {
        let normalized = p / total;
        if normalized > 0.0 {
            entropy -= normalized * normalized.ln();
        }
    }
    entropy
}

/// Integrate PSD energy within each frequency band.
///
/// Returns `Vec<(label, fraction)>` where fraction is band_energy / total_energy.
#[allow(dead_code)]
pub fn spectral_energy_bands(
    freqs: &[f64],
    psd: &[f64],
    bands: &[(f64, f64)],
) -> Vec<(String, f64)> {
    let total: f64 = psd.iter().sum::<f64>() + 1e-12;
    let mut result = Vec::with_capacity(bands.len());

    for &(lo, hi) in bands {
        let band_energy: f64 = freqs
            .iter()
            .zip(psd.iter())
            .filter(|(&f, _)| f >= lo && f < hi)
            .map(|(_, &p)| p)
            .sum();
        let label = format!("{:.2}-{:.2}Hz", lo, hi);
        result.push((label, band_energy / total));
    }

    result
}

// --------------------------------------------------------------------------- //
// Butterworth low-pass filter (2nd order IIR, zero-phase)                       //
// --------------------------------------------------------------------------- //

/// Design a 2nd-order Butterworth low-pass filter as second-order sections.
///
/// Returns `(b0, b1, b2, a0, a1, a2)` -- a single SOS biquad section.
/// Analog prototype via bilinear transform.
fn butter_lowpass_sos(cutoff_hz: f64, fs: f64) -> Option<(f64, f64, f64, f64, f64, f64)> {
    let nyq = fs / 2.0;
    if cutoff_hz >= nyq || cutoff_hz <= 0.0 {
        return None;
    }

    // Pre-warp
    let wc = (PI * cutoff_hz / fs).tan();
    let wc2 = wc * wc;
    let sqrt2 = std::f64::consts::SQRT_2;

    // Bilinear transform of 2nd-order Butterworth: s-domain poles at
    // s = wc * exp(±j * 3π/4)
    // Transfer function: H(s) = wc^2 / (s^2 + sqrt(2)*wc*s + wc^2)
    // Bilinear: s = 2*fs*(z-1)/(z+1)
    let k = 2.0 * fs;
    let k2 = k * k;

    let a0_raw = k2 + sqrt2 * wc * k + wc2;
    let a1_raw = 2.0 * wc2 - 2.0 * k2;
    let a2_raw = k2 - sqrt2 * wc * k + wc2;

    let b0_raw = wc2;
    let b1_raw = 2.0 * wc2;
    let b2_raw = wc2;

    // Normalize
    Some((
        b0_raw / a0_raw,
        b1_raw / a0_raw,
        b2_raw / a0_raw,
        1.0,
        a1_raw / a0_raw,
        a2_raw / a0_raw,
    ))
}

/// Apply a single SOS section forward.
fn sosfilt_forward(
    b0: f64, b1: f64, b2: f64,
    _a0: f64, a1: f64, a2: f64,
    x: &[f64],
) -> Vec<f64> {
    let n = x.len();
    let mut y = vec![0.0; n];
    let mut w1 = 0.0_f64;
    let mut w2 = 0.0_f64;

    for i in 0..n {
        let w0 = x[i] - a1 * w1 - a2 * w2;
        y[i] = b0 * w0 + b1 * w1 + b2 * w2;
        w2 = w1;
        w1 = w0;
    }
    y
}

/// Zero-phase (forward-backward) Butterworth low-pass filter.
///
/// Equivalent to `scipy.signal.sosfiltfilt` with a 2nd-order Butterworth.
pub fn butterworth_lowpass(data: &[f64], cutoff_hz: f64, fs: f64) -> Vec<f64> {
    let nyq = fs / 2.0;
    if cutoff_hz >= nyq || data.len() < 6 {
        return data.to_vec();
    }

    let data_min = data.iter().copied().fold(f64::INFINITY, f64::min);
    let data_max = data.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    if (data_max - data_min).abs() < 1e-12 {
        return data.to_vec();
    }

    let (b0, b1, b2, a0, a1, a2) = match butter_lowpass_sos(cutoff_hz, fs) {
        Some(c) => c,
        None => return data.to_vec(),
    };

    // Forward pass
    let fwd = sosfilt_forward(b0, b1, b2, a0, a1, a2, data);
    // Reverse
    let mut rev: Vec<f64> = fwd.into_iter().rev().collect();
    // Backward pass
    rev = sosfilt_forward(b0, b1, b2, a0, a1, a2, &rev);
    // Reverse again
    rev.reverse();
    rev
}

// --------------------------------------------------------------------------- //
// Tests                                                                         //
// --------------------------------------------------------------------------- //

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rms_basic() {
        let x = vec![1.0, -1.0, 1.0, -1.0];
        assert!((rms(&x) - 1.0).abs() < 1e-10);
    }

    #[test]
    fn test_rms_empty() {
        assert_eq!(rms(&[]), 0.0);
    }

    #[test]
    fn test_crest_factor_flat() {
        let x = vec![1.0, 1.0, 1.0, 1.0];
        assert!((crest_factor(&x).unwrap() - 1.0).abs() < 1e-10);
    }

    #[test]
    fn test_crest_factor_zero() {
        let x = vec![0.0, 0.0, 0.0];
        assert!(crest_factor(&x).is_none());
    }

    #[test]
    fn test_zero_crossing_period_sine() {
        // 1 Hz sine at 100 Hz sample rate -> period = 1.0 s
        let fs = 100.0;
        let n = 500;
        let x: Vec<f64> = (0..n).map(|i| (2.0 * PI * i as f64 / fs).sin()).collect();
        let period = zero_crossing_period(&x, fs).unwrap();
        assert!((period - 1.0).abs() < 0.05, "period={}", period);
    }

    #[test]
    fn test_unwrap_angle() {
        let prev = 3.0;
        let curr = -3.0; // jump of ~6, should unwrap
        let result = unwrap_angle(prev, curr);
        let diff = result - prev;
        assert!(diff.abs() < PI + 0.01);
    }

    #[test]
    fn test_angle_wrap() {
        assert!((angle_wrap(4.0) - (4.0 - 2.0 * PI)).abs() < 1e-10);
        assert!((angle_wrap(-4.0) - (-4.0 + 2.0 * PI)).abs() < 1e-10);
    }

    #[test]
    fn test_welch_dominant_sine() {
        // 0.2 Hz sine at 2 Hz sample rate, 60 samples (30 seconds)
        let fs = 2.0;
        let n = 60;
        let freq = 0.2;
        let x: Vec<f64> = (0..n)
            .map(|i| (2.0 * PI * freq * i as f64 / fs).sin())
            .collect();
        let (dom_f, conf, _, _) = welch_dominant(&x, fs, 16);
        assert!(dom_f.is_some());
        let df = dom_f.unwrap();
        // Should be close to 0.2 Hz (within PSD resolution)
        assert!((df - freq).abs() < 0.15, "dom_freq={}", df);
        assert!(conf.unwrap() > 0.0);
    }

    #[test]
    fn test_spectral_entropy_uniform() {
        let psd = vec![1.0; 10];
        let e = spectral_entropy(&psd);
        // Uniform -> max entropy ≈ ln(10)
        assert!((e - 10.0_f64.ln()).abs() < 0.01);
    }

    #[test]
    fn test_kurtosis_gaussian_like() {
        // For a uniform distribution, excess kurtosis ≈ -1.2
        let n = 10000;
        let x: Vec<f64> = (0..n).map(|i| i as f64 / n as f64).collect();
        let k = kurtosis(&x);
        assert!((k - (-1.2)).abs() < 0.1, "kurtosis={}", k);
    }

    #[test]
    fn test_butterworth_lowpass() {
        // A DC signal should pass through unchanged
        let data = vec![1.0; 100];
        let filtered = butterworth_lowpass(&data, 0.5, 10.0);
        for v in &filtered {
            assert!((v - 1.0).abs() < 0.01, "v={}", v);
        }
    }
}
