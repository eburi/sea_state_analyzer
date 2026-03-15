# sea_state_analyzer – Signal K Wave State Monitor

A Python application that connects to a Signal K marine server, reads an
onboard IMU (ICM-20948 accelerometer/gyroscope/magnetometer), estimates wave
conditions including multi-component spectral partitioning (wind-wave, swell 1,
swell 2), and publishes wave estimates back to Signal K.  Runs as a **Home
Assistant App** on a Raspberry Pi 5.

> **Domain caution:** Wave height, period, and partition outputs are **estimated
> from vessel motion** using Kalman-filtered heave, Doppler correction, hull
> resonance suppression, and spectral analysis.  Sail trim, point of sail, hull
> form, autopilot behaviour, displacement, and loading all modulate the observed
> motion.  Outputs improve with calibration data but are not equivalent to
> dedicated wave buoy measurements.

---

## Architecture

```
src/
  config.py            – all tunable parameters (Config dataclass + DEFAULT_CONFIG)
  paths.py             – canonical Signal K path constants (self-data only)
  models.py            – typed data structures (RawDeltaMessage → InstantSample → WindowFeatures → MotionEstimate)
  signalk_client.py    – WebSocket client, reconnect backoff, explicit subscriptions
  signalk_auth.py      – Signal K device access request flow + JWT token persistence
  signalk_publisher.py – Delta/meta building for publishing wave estimates back to Signal K
  state_store.py       – latest-known self-state, freshness tracking, InstantSample snapshots
  feature_extractor.py – Layer A (derivatives), Layer B (rolling stats/PSD), Layer C (inferred proxies)
  heave_estimator.py   – Kalman heave filter, trochoidal Hs, Doppler correction, spectral partitioning
  vessel_config.py     – Hull parameters, RAO gain model, hull classification
  imu_registry.py      – IMU chip registry (WHO_AM_I values, I2C addresses)
  imu_detect.py        – I2C bus scanning and chip identification
  imu_reader.py        – ICM-20948 driver + async wrapper with auto-detect support
  recorder.py          – batched JSONL + Parquet output
  plotter.py           – console summaries + optional matplotlib PNGs
  main.py              – CLI entry point: live / inspect / replay modes
tests/                 – pytest unit tests (494 tests)
conftest.py            – adds src/ to sys.path for pytest
sea_state_analyzer/    – Home Assistant App packaging (config.yaml, Dockerfile, run.sh)
```

---

## Setup

```bash
# 1. Create a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Verify Signal K reachability (optional)
curl http://primrose.local:3000/signalk

# All commands below are run from the project root.
# The entry point is src/main.py.
```

---

## Usage

### Live mode (default)

Connect to the Signal K server and start ingesting vessel self data:

```bash
python src/main.py
# or explicitly:
python src/main.py live

# With matplotlib plots generated periodically:
python src/main.py live --plots

# Override Signal K URL:
python src/main.py live --url http://192.168.1.100:3000
```

Live mode produces console output every 5 seconds:

```
╔══════════════════════════════════════════════════════════╗
║  SeaState – Wave Motion Monitor   14:32:07 UTC    ║
╠══════════════════════════════════════════════════════════╣
║  ● CONNECTED      samples=  1234  rate=2.0Hz  reconnects=0
╠══════════════════════════════════════════════════════════╣
║  ATTITUDE    roll=   3.2°   pitch=  -1.1°
║  NAVIGATION  hdg=  245.0°    cog=  246.1°    sog=   4.50m/s
║  WIND TRUE      6.2m/s  angle=  142°   APP   8.1m/s  angle=  118°
╠══════════════════════════════════════════════════════════╣
║  MOTION 30s  roll_RMS=   4.5°  pitch_RMS=   2.1°
║              roll_T=   9.8s   pitch_T=   8.2s
╠══════════════════════════════════════════════════════════╣
║  SEVERITY       0.312 [██████░░░░░░░░░░░░░░]
║  REGIME      moderate    trend=stable
║  DIRECTION   beam_like                  conf=  0.72
║  REGULARITY  regular       confusion=  0.21
║  COMFORT        0.278  confidence=  0.68
╚══════════════════════════════════════════════════════════╝
```

### Inspect mode

Observe all Signal K self paths for 60 seconds and write a report:

```bash
python src/main.py inspect
# Custom duration:
python src/main.py inspect --duration 120
```

Output: `output/<timestamp>/path_inventory.md`

The report lists every self path observed, its update frequency, source
identifiers, and whether it is used in normal mode.  Use this to verify what
sensors are actually available on your installation before running live mode.

### Replay mode

Replay a previously recorded raw delta file to re-run feature extraction
offline (no Signal K connection required):

```bash
python src/main.py replay --input output/20240601_120000/raw_self_deltas.jsonl
# With plot generation:
python src/main.py replay --input output/20240601_120000/raw_self_deltas.jsonl --plots
```

---

## Output files

All outputs are written to a session-stamped directory under `output/`:

| File | Format | Description |
|------|--------|-------------|
| `raw_self_deltas.jsonl` | JSONL | Raw Signal K delta messages as received |
| `samples.parquet` | Parquet | Normalized InstantSamples at 2 Hz |
| `features_10s.parquet` | Parquet | Rolling 10-second window features |
| `features_30s.parquet` | Parquet | Rolling 30-second window features |
| `features_60s.parquet` | Parquet | Rolling 60-second window features |
| `features_300s.parquet` | Parquet | Rolling 5-minute window features |
| `events.jsonl` | JSONL | Motion estimate events (every 5 s) |
| `path_inventory.md` | Markdown | Inspect-mode path report |
| `plot_*.png` | PNG | Optional matplotlib plots |

### events.jsonl schema

Each line is a JSON object with these fields (None values omitted):

| Field | Units | Description |
|-------|-------|-------------|
| `timestamp` | ISO-8601 | Estimate time (UTC) |
| `latitude`, `longitude` | degrees | Vessel position at estimate time |
| `motion_severity` | 0–1 | Composite motion severity score |
| `motion_regime` | string | calm / moderate / active / heavy |
| `significant_height` | metres | Estimated Hs from IMU accelerometer |
| `heave` | metres | Current heave displacement (Kalman) |
| `encounter_period_estimate` | seconds | Dominant encounter period |
| `true_wave_period` | seconds | Doppler-corrected true wave period |
| `true_wavelength` | metres | True wavelength (deep-water dispersion) |
| `encounter_direction` | string | beam_like / head_or_following_like / ... |
| `comfort_proxy` | 0–1 | Motion comfort index |
| `wind_wave_height` | metres | Hs of wind-wave spectral partition |
| `wind_wave_period` | seconds | Peak period of wind-wave partition |
| `wind_wave_confidence` | 0–1 | Confidence in wind-wave partition |
| `swell_1_height` | metres | Hs of primary swell partition |
| `swell_1_period` | seconds | Peak period of primary swell |
| `swell_1_confidence` | 0–1 | Confidence in primary swell partition |
| `swell_2_height` | metres | Hs of secondary swell partition |
| `swell_2_period` | seconds | Peak period of secondary swell |
| `swell_2_confidence` | 0–1 | Confidence in secondary swell partition |

All Parquet files include `timestamp` (ISO-8601 string) and `timestamp_epoch`
(float Unix seconds) columns, plus freshness metadata columns (`age_*`,
`valid_*`) on every sample row.

---

## Wave estimation pipeline

### IMU integration

The ICM-20948 9-DOF IMU (accelerometer + gyroscope + magnetometer) is read
directly over I2C at 25 Hz.  The IMU is mounted vertically on a wall; gravity
calibration uses dot-product projection to determine the gravity axis
automatically regardless of mounting orientation.

Vertical acceleration is extracted by subtracting the gravity component,
then fed into the heave estimation pipeline.

### Heave estimation (Kalman filter)

Vertical acceleration is double-integrated into heave displacement using a
Kalman filter with zero-mean drift correction on the third integral (velocity
and position bias).  The bias window (5000 samples) prevents long-term drift
while preserving wave-frequency content.

### Significant wave height (Hs)

Hs is computed as `4 * sqrt(m0)` from the zeroth spectral moment of the
Kalman-filtered displacement PSD, after hull resonance suppression (see below).
A trochoidal model provides an independent cross-check from peak vertical
acceleration.

### Hull resonance suppression

Catamaran hull resonance (~0.33 Hz / 3 s for a 14 m hull) amplifies the
displacement PSD at frequencies that don't correspond to real waves.  A
Gaussian notch filter suppresses this resonance peak before computing Hs.
Hull parameters (LOA, beam, hull type) are defined in `vessel_config.py`.

### Doppler correction

Encounter frequency (observed on the moving boat) differs from true wave
frequency.  The correction uses `delta_v = STW * cos(TWA)` to recover the
source wave period and wavelength via deep-water dispersion relation.
Speed through water (STW) is preferred over SOG when available.

### Multi-peak spectral partitioning

The displacement PSD (after hull resonance suppression) is partitioned into
up to 3 spectral components using `scipy.signal.find_peaks` with
prominence-based peak detection:

1. **Wind wave** — highest-frequency partition
2. **Swell 1** — primary swell (mid-frequency)
3. **Swell 2** — secondary swell (lowest-frequency)

The spectrum is split at local minima between adjacent peaks.  Each partition
gets its own `Hs = 4*sqrt(m0)` from integrated spectral energy, plus peak
period and confidence (from energy share x peak sharpness).

This labeling matches the convention used by Windy, Open-Meteo, and Copernicus
(MFWAM) forecast models, enabling direct comparison of observed vs forecast
partition data.

### Signal K publishing

Wave estimates are published back to Signal K via authenticated WebSocket
delta messages.  Published paths include:

| Signal K path | Description |
|---------------|-------------|
| `environment.water.waves.significantHeight` | Total Hs (metres) |
| `environment.water.waves.period` | Encounter period (seconds) |
| `environment.water.waves.truePeriod` | Doppler-corrected period |
| `environment.water.waves.trueWavelength` | True wavelength (metres) |
| `environment.water.waves.motionSeverity` | Severity index (0-1) |
| `environment.water.waves.motionRegime` | calm/moderate/active/heavy |
| `environment.water.waves.encounterDirection` | Direction relative to heading |
| `environment.water.waves.comfortProxy` | Comfort index (0-1) |
| `environment.water.waves.windWave.height` | Wind-wave Hs (metres) |
| `environment.water.waves.windWave.period` | Wind-wave peak period |
| `environment.water.waves.swell1.height` | Primary swell Hs (metres) |
| `environment.water.waves.swell1.period` | Primary swell peak period |
| `environment.water.waves.swell2.height` | Secondary swell Hs (metres) |
| `environment.water.waves.swell2.period` | Secondary swell peak period |
| `environment.heave` | Current heave displacement |

Meta deltas with units, descriptions, and display names are sent on startup
so Signal K dashboards can display proper labels.

---

## Configuration

All parameters are in `config.py`.  Notable defaults:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `base_url` | `http://primrose.local:3000` | Signal K base URL |
| `ws_url` | `ws://primrose.local:3000/signalk/v1/stream?subscribe=none` | WebSocket URL |
| `sample_rate_hz` | `2.0` | InstantSample production rate |
| `rolling_windows_s` | `[10, 30, 60, 300]` | Feature window sizes (s) |
| `stale_threshold_s` | `10.0` | Age before a field is flagged stale |
| `console_interval_s` | `5.0` | Console summary interval |
| `enable_live_plots` | `False` | Enable periodic PNG generation |
| `inspect_duration_s` | `60.0` | Default inspect observation window |
| `severity_roll_rms_max` | `0.35 rad (~20°)` | RMS reference for severity=1 |
| `severity_pitch_rms_max` | `0.175 rad (~10°)` | RMS reference for severity=1 |

---

## Feature description

### Layer A – Instantaneous derived values

Computed at the sample rate (2 Hz) from consecutive snapshots:

- `roll_rate`, `pitch_rate`, `yaw_rate_derived` (rad/s) – finite-difference derivatives with angle unwrapping and trailing moving-average smoothing
- `roll_acceleration`, `pitch_acceleration` (rad/s²) – second derivative
- `heading_minus_cog` (rad) – leeway/drift proxy
- `wind_angle_true_bow`, `wind_angle_apparent_bow` (rad) – wind angle relative to bow
- `roll_normalized`, `pitch_normalized` – motion per unit SOG

### Layer B – Rolling-window statistics

Computed per configured window (10 s, 30 s, 60 s, 5 min):

- Mean, std, RMS, peak-to-peak, kurtosis, crest factor
- Zero-crossing period estimate
- Welch PSD dominant frequency and period with confidence score
- Spectral energy per frequency band (0.05–0.1, 0.1–0.2, 0.2–0.4, 0.4–1.0 Hz)
- Spectral entropy (regularity indicator)
- Dominant period stability (std across recent windows)
- Yaw-rate variance, SOG variance, heading-COG variance, wind variance

### Layer C – Inferred motion proxies

All labelled as inferred, not measured:

- **Motion severity** (0–1): weighted blend of roll RMS, pitch RMS, roll spectral energy, yaw-rate variance; exponentially smoothed
- **Motion regime**: calm / moderate / active / heavy
- **Encounter direction proxy**: beam_like / head_or_following_like / quartering_like / confused_like / mixed
- **Motion regularity**: regular / mixed / confused (from spectral entropy and period stability)
- **Dominant motion period**: separate roll and pitch estimates with confidence, plus combined encounter period estimate
- **Comfort proxy** (0–1): blend of severity and crest factor
- **Severity trend**: improving / stable / worsening (comparing 5-min to 15-min window)
- **Overall confidence** (0–1): data completeness and spectral quality

---

## Running tests

```bash
pip install pytest
pytest tests/ -v
# conftest.py at the project root adds src/ to sys.path automatically.
```

---

## Assumptions and limitations

- **Vessel self only.** No other vessel data is used.
- **Indirect wave inference.** Wave height, direction, and period are not directly observable from attitude sensors alone.
- **Sensor availability varies.** Run inspect mode first to see which paths are actually present on your installation.
- **Sampling rate.** 2 Hz is sufficient for roll/pitch periods > 2 s but will miss short-period chop.
- **Bias.** A dataset collected entirely downwind or during calms will produce biased learned regimes.
- **Autopilot.** Autopilot corrections affect yaw-rate and may create artefacts in period estimates.
- **GPS quality.** COG and SOG are unreliable at very low speeds; heading-COG comparisons are only meaningful underway.

---

## Deployment

The application runs as a **Home Assistant App** (formerly "Add-on") alongside
the Signal K App on a Raspberry Pi 5 running HAOS.

### Deploying to Home Assistant

```bash
# Copy files to HA host and rebuild
bash sea_state_analyzer/deploy.sh root@192.168.46.222

# Rebuild and restart on HA
ssh root@192.168.46.222 "ha apps rebuild local_sea_state_analyzer && ha apps start local_sea_state_analyzer"
```

The app packaging lives in `sea_state_analyzer/` with:
- `config.yaml` — app metadata, device mappings (`/dev/i2c-1` for IMU)
- `Dockerfile` — `ARG BUILD_FROM` / `FROM $BUILD_FROM` pattern
- `run.sh` — entry point
- `requirements.txt` — Python dependencies

### Design decisions

- The only external dependency is Signal K's WebSocket delta API — no Signal K library imports, no plugin SDK.
- All configuration lives in `config.py` and environment variables.
- Single long-running async Python process.
- Output files written to `/root/share/sea_state_analyzer/` on HA (mapped volume).
- JWT token persisted at `/data/signalk_token.json` for reconnection.
- Graceful degradation: works on macOS without IMU (attitude-only estimation).

---

## Project goals

The end goal is a continuously-running sea-state monitor that produces data useful for:

1. **Logbook entries** — sea state (Beaufort / Douglas scale), dominant wave direction, wave period, and ideally separate swell vs wind-wave components.
2. **Boat performance monitoring** — a companion add-on will eventually learn polar performance by correlating boat speed with wind and sea state. Having reliable sea-state data from this project is a prerequisite.
3. **Weather routing** — sea-state forecasts are only useful if the system can compare them against observed conditions. Continuous wave estimation provides the ground truth for that comparison.

### Reference: bareboat-necessities wave estimation

The approach described at <https://bareboat-necessities.github.io/my-bareboat/bareboat-math.html> is a key reference. It outlines two methods for estimating actual wave height from a moving boat:

1. **Trochoidal wave model** — reconstruct wave amplitude from observed max/min vertical acceleration and wave frequency, using known trochoid geometry.
2. **Kalman filter heave integration** — double-integrate vertical acceleration into displacement, with a zero-mean constraint on the third integral to prevent drift.

Both methods require **Doppler correction**: the boat moves relative to wave fronts, so observed (encounter) frequency differs from true wave frequency. The correction uses `delta_v = SPD * cos(TWA)` (boat speed projected onto wave propagation direction) to recover the source wavelength from the observed frequency.

### Current state vs bareboat-necessities approach

What sea_state_analyzer **implements**:
- Kalman-filtered heave estimation (double-integrated vertical acceleration with drift correction)
- Trochoidal wave height model as cross-check
- Doppler correction using STW and TWA to recover true wave period/wavelength
- Hull resonance suppression (Gaussian notch at catamaran resonant frequency)
- Multi-peak spectral partitioning (wind-wave, swell 1, swell 2)
- RAO-aware confidence adjustment based on hull parameters
- Classification pipeline (severity, regime, direction, regularity, comfort, trend)
- Signal K publishing with meta deltas for dashboard integration
- Position recording on every estimate for forecast comparison

What sea_state_analyzer is **missing** for full wave measurement:
- Wave direction estimation (requires cross-spectral analysis between roll/pitch/heave)
- Aranovskiy online frequency estimator (currently using Welch PSD)
- Swell vs wind-wave direction separation
- Douglas sea-state scale mapping for logbook entries

### Incremental path forward

1. ~~Derive speed through water~~ ✓ (uses STW from Signal K when available)
2. ~~Doppler correction~~ ✓ (encounter → true wave period/wavelength)
3. ~~IMU accelerometer integration~~ ✓ (ICM-20948 at 25 Hz over I2C)
4. ~~Trochoidal wave height estimation~~ ✓
5. ~~Kalman heave estimation~~ ✓
6. ~~Spectral partitioning (swell vs wind-wave)~~ ✓
7. Douglas sea-state scale mapping for logbook use
8. Wave direction estimation from cross-spectral roll/pitch/heave analysis
9. Forecast comparison pipeline (Open-Meteo live, Copernicus for training backfill)
10. Calibration model training on multi-boat partition data

---

## Future development

1. **Douglas scale mapping:** Map Hs + period to Douglas sea-state numbers for logbook entries.
2. **Wave direction estimation:** Cross-spectral analysis of roll, pitch, and heave to infer wave propagation direction.
3. **Forecast comparison:** Ingest Open-Meteo marine API (live) and Copernicus MFWAM (backfill) partition data; compare observed vs forecast Hs, period, and partition breakdown at recorded positions.
4. **Calibration models:** Train hull-specific correction models on accumulated partition data with forecast labels.
5. **Multi-boat ML:** Collect partition-level features + position from multiple boats to build a generalized wave estimation model.
6. **Signal K plugin (optional):** Wrap the core in a Signal K server plugin if tight integration is preferred. This is a packaging change only — the analysis code stays the same.
7. **Polar performance companion:** A second app that correlates boat speed with wind and sea state to learn vessel polar performance over time. Depends on sea-state output from this project.
