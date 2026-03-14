# boat_state – Signal K Wave Motion Learner

A Python prototype that connects to a Signal K server, ingests vessel self
data in real time, extracts motion features, and derives inferred sea-state
proxies from onboard sensors.

> **Domain caution:** This tool infers **vessel motion response to sea state**.
> It does NOT produce direct measurements of wave height, period, or direction.
> Sail trim, point of sail, hull form, autopilot behaviour, displacement, and
> loading all modulate the observed motion.  All outputs are inferred motion
> proxies, not authoritative environmental measurements.

---

## Architecture

```
src/
  config.py           – all tunable parameters
  paths.py            – canonical Signal K path constants
  models.py           – typed data structures
  state_store.py      – latest-known self-state, freshness tracking
  signalk_client.py   – WebSocket client, reconnect, subscription
  feature_extractor.py – Layer A/B/C feature extraction
  recorder.py         – JSONL + Parquet output
  plotter.py          – console summaries + matplotlib PNGs
  main.py             – CLI entry point (live / inspect / replay)
tests/              – pytest unit tests
conftest.py         – adds src/ to sys.path for pytest
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
║  BoatState – Wave Motion Monitor   14:32:07 UTC    ║
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

All Parquet files include `timestamp` (ISO-8601 string) and `timestamp_epoch`
(float Unix seconds) columns, plus freshness metadata columns (`age_*`,
`valid_*`) on every sample row.

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

## Deployment goal

The long-term target is a **Home Assistant Add-on** (formerly called "Addon") that runs alongside the Signal K Add-on on the same host and continuously analyses wave state in the background. The two add-ons communicate over the local network — boat_state connects to Signal K's WebSocket API just as it does today.

A **Signal K plugin** is a possible alternative packaging, but the project is designed to stay independent of Signal K internals so it can outlive any future migration away from Signal K. Converting to a Signal K plugin later would be straightforward since the only integration point is the WebSocket delta stream.

Design decisions that support this:

- The only external dependency is Signal K's WebSocket delta API — no Signal K library imports, no plugin SDK.
- All configuration lives in `config.py` and can be mapped to Home Assistant Add-on options (`options.json` / UI schema) without code changes.
- The process is a single long-running async Python application, which fits the Home Assistant Add-on model (one container, one process).
- Output files are written to a configurable directory that can be mapped to a Home Assistant `/share` or `/data` volume.
- No macOS-specific code; runs on Raspberry Pi 5 / Linux as-is.

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

What boat_state **already does well**:
- Classification pipeline (severity, regime, direction, regularity, comfort, trend) — the bareboat article does not attempt this
- Spectral band decomposition (0.05–0.1, 0.1–0.2, 0.2–0.4, 0.4–1.0 Hz) that can separate swell from wind waves
- Robust reconnection, missing-data handling, and recording infrastructure

What boat_state is **missing** for actual wave measurement:
- No vertical acceleration data (would need `navigation.acceleration` or raw IMU from Signal K)
- No Doppler correction — all period/frequency estimates are encounter values, not true wave values
- No heave/displacement estimation (no Kalman filter or double integration)
- No speed-through-water derivation (needed for Doppler correction, but could be computed from existing heading/COG/SOG data)
- Head vs following seas are indistinguishable (the Doppler sign resolves this, but it is not implemented)

### Incremental path forward

1. Derive speed through water (SPD) from heading–COG difference (data already available)
2. Add Doppler correction to convert encounter periods to true wave periods
3. Subscribe to accelerometer data if available on the Signal K server
4. Implement trochoidal wave height estimation (requires accel data)
5. Implement Kalman heave estimation (requires accel data)
6. Use spectral bands to report swell vs wind-wave components separately
7. Map outputs to Douglas sea-state scale for logbook use

---

## Future development

1. **Clustering (Stage 2):** Use `features_60s.parquet` with KMeans / Gaussian Mixture / HDBSCAN to discover natural motion regimes.
2. **Label collection (Stage 3):** Apply manual labels (calm / moderate / rough / surfing / confused) to regime clusters.
3. **Supervised models:** Train random forest or gradient boosting on the labelled feature matrix.
4. **Raspberry Pi 5 deployment:** The pipeline is async and has no macOS dependencies; deploy with the same `requirements.txt` on Pi OS.
5. **Home Assistant Add-on packaging:** Dockerfile, `config.yaml`, and `options.json` for the HA Add-on store. Expose motion severity and regime as HA sensors via the Supervisor API or MQTT.
6. **Signal K plugin (optional):** Wrap the core in a Signal K server plugin if tight integration is preferred. This is a packaging change only — the analysis code stays the same.
7. **Polar performance companion:** A second add-on that correlates boat speed with wind and sea state to learn vessel polar performance over time. Depends on sea-state output from this project.
