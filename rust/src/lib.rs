mod doppler;
mod dsp;
mod heave;
#[allow(dead_code)]
mod scales;
#[allow(dead_code)]
mod vessel;

use pyo3::prelude::*;

#[pyfunction]
fn rms(values: Vec<f64>) -> f64 {
    dsp::rms(&values)
}

#[pyfunction]
fn butterworth_lowpass(values: Vec<f64>, cutoff_hz: f64, fs: f64) -> Vec<f64> {
    dsp::butterworth_lowpass(&values, cutoff_hz, fs)
}

#[pyfunction]
fn doppler_correct(encounter_freq_hz: f64, delta_v: f64) -> Option<(f64, f64, f64)> {
    doppler::doppler_correct(encounter_freq_hz, delta_v)
}

#[pyfunction]
#[pyo3(signature = (stw=None, wind_angle_true=None))]
fn compute_delta_v(stw: Option<f64>, wind_angle_true: Option<f64>) -> Option<f64> {
    doppler::compute_delta_v(stw, wind_angle_true)
}

#[pyfunction]
#[pyo3(signature = (delta_v=None, stw=None))]
fn classify_wave_heading(delta_v: Option<f64>, stw: Option<f64>) -> Option<String> {
    doppler::classify_wave_heading(delta_v, stw).map(|s| s.to_string())
}

#[pyfunction]
fn trochoidal_wave_height(
    accel_max_observed: f64,
    frequency_hz: f64,
    delta_v: f64,
    min_amplitude: f64,
) -> Option<(f64, f64, f64, f64, f64, f64, f64, String)> {
    heave::trochoidal_wave_height(accel_max_observed, frequency_hz, delta_v, min_amplitude).map(
        |v| {
            (
                v.significant_height,
                v.wave_amplitude,
                v.wavelength,
                v.wave_speed,
                v.b_parameter,
                v.accel_max,
                v.frequency_hz,
                v.method,
            )
        },
    )
}

#[pyclass]
struct PyKalmanHeaveEstimator {
    inner: heave::KalmanHeaveEstimator,
}

#[pymethods]
impl PyKalmanHeaveEstimator {
    #[new]
    #[pyo3(signature = (
        dt=0.02,
        pos_integral_trans_var=1e-6,
        pos_trans_var=1e-4,
        vel_trans_var=1e-2,
        pos_integral_obs_var=1e-1,
        accel_bias_window=500,
    ))]
    fn new(
        dt: f64,
        pos_integral_trans_var: f64,
        pos_trans_var: f64,
        vel_trans_var: f64,
        pos_integral_obs_var: f64,
        accel_bias_window: usize,
    ) -> Self {
        Self {
            inner: heave::KalmanHeaveEstimator::new(
                dt,
                pos_integral_trans_var,
                pos_trans_var,
                vel_trans_var,
                pos_integral_obs_var,
                accel_bias_window,
            ),
        }
    }

    #[pyo3(signature = (initial_displacement=0.0, initial_velocity=0.0))]
    fn reset(&mut self, initial_displacement: f64, initial_velocity: f64) {
        self.inner.reset(initial_displacement, initial_velocity);
    }

    fn update(&mut self, vertical_accel: f64) -> f64 {
        self.inner.update(vertical_accel)
    }

    #[pyo3(signature = (min_samples=100))]
    fn get_estimate(
        &self,
        min_samples: usize,
    ) -> Option<(f64, f64, f64, f64, f64, f64, usize, bool, String)> {
        self.inner.get_estimate(min_samples).map(|v| {
            (
                v.heave_displacement,
                v.heave_amplitude,
                v.significant_height,
                v.heave_std,
                v.heave_max,
                v.heave_min,
                v.n_samples,
                v.converged,
                v.method,
            )
        })
    }

    #[getter]
    fn displacement(&self) -> f64 {
        self.inner.displacement()
    }

    #[getter]
    fn velocity(&self) -> f64 {
        self.inner.velocity()
    }

    #[getter]
    fn n_processed(&self) -> usize {
        self.inner.n_processed()
    }
}

#[pymodule]
fn sea_state_engine(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(rms, m)?)?;
    m.add_function(wrap_pyfunction!(butterworth_lowpass, m)?)?;
    m.add_function(wrap_pyfunction!(doppler_correct, m)?)?;
    m.add_function(wrap_pyfunction!(compute_delta_v, m)?)?;
    m.add_function(wrap_pyfunction!(classify_wave_heading, m)?)?;
    m.add_function(wrap_pyfunction!(trochoidal_wave_height, m)?)?;
    m.add_class::<PyKalmanHeaveEstimator>()?;
    Ok(())
}
