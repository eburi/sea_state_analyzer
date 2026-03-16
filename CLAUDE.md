# Copilot Instructions – sea_state_analyzer

## Project overview

`sea_state_analyzer` is a Python 3.11+ prototype that connects to a Signal K marine server (`http://primrose.local:3000`), ingests **vessel self data only**, and derives inferred sea-state motion proxies from onboard attitude, movement, and wind sensors.

> **Domain caution:** All outputs are *inferred motion proxies*, not direct wave measurements — for now. The goal is to progressively add actual wave estimation (height, true period, direction) as described below.

---

## Project goals

The end goal is a continuously-running **Home Assistant Add-on** that produces:

1. **Sea state for logbook** — wave height, direction, period; ideally swell vs wind-wave separation; Douglas / Beaufort scale mapping.
2. **Input for boat performance monitoring** — a future companion add-on will learn polar performance by correlating boat speed with wind and sea state. Reliable sea-state output from this project is a prerequisite.
3. **Ground truth for weather routing** — compare observed conditions against forecast sea state.

### Key reference: bareboat-necessities wave estimation

The approach at <https://bareboat-necessities.github.io/my-bareboat/bareboat-math.html> is a primary reference. It describes:

- **Trochoidal wave model** — reconstruct wave amplitude from max/min vertical acceleration + observed frequency.
- **Kalman filter heave integration** — double-integrate vertical acceleration into displacement with zero-mean drift correction.
- **Doppler correction** — convert encounter frequency to true wave frequency using `delta_v = SPD * cos(TWA)`.
- **Aranovskiy online frequency estimator** as a lightweight alternative to FFT.

### Current gaps to close (incremental)

1. Derive speed through water (SPD) from heading–COG difference (data already available)
2. Add Doppler correction to convert encounter periods to true wave periods
3. Subscribe to accelerometer data (`navigation.acceleration` or raw IMU) if available on the Signal K server
4. Implement trochoidal wave height estimation (requires accel data)
5. Implement Kalman heave estimation (requires accel data)
6. Report swell vs wind-wave components from existing spectral bands
7. Map outputs to Douglas sea-state scale

### Deployment target

- **Home Assistant Add-on** running alongside the Signal K Add-on
- Designed to stay independent of Signal K internals (WebSocket delta API is the only integration point)
- May be converted to a Signal K plugin later, but the project should outlive any future SK migration

---

## Architecture

```
src/
  config.py            – all tunable parameters (Config dataclass + DEFAULT_CONFIG)
  paths.py             – canonical Signal K path constants (self-data only)
  models.py            – typed data structures (RawDeltaMessage → InstantSample → WindowFeatures → MotionEstimate)
  signalk_client.py    – WebSocket client, reconnect backoff, explicit subscriptions
  state_store.py       – latest-known self-state, freshness tracking, InstantSample snapshots
  feature_extractor.py – Layer A (derivatives), Layer B (rolling stats/PSD), Layer C (inferred proxies)
  imu_registry.py      – IMU chip registry (WHO_AM_I values, I2C addresses) for auto-detection
  imu_detect.py        – I2C bus scanning and chip identification using the registry
  imu_reader.py        – ICM-20948 driver + async wrapper with auto-detect support
  recorder.py          – batched JSONL + Parquet output
  plotter.py           – console summaries + optional matplotlib PNGs
  main.py              – CLI entry point: live / inspect / replay modes
tests/
  test_parsing.py      – delta parsing, self-path filtering, state store
  test_features.py     – angle unwrapping, PSD, spectral features, regime classification
  test_rolling.py      – rolling window statistics and multi-window behaviour
  test_imu.py          – ICM-20948 driver, async wrapper, IMU merge logic
  test_imu_detect.py   – IMU registry, I2C scanning, chip identification
conftest.py            – adds src/ to sys.path for pytest
```

---

## Key conventions

- **Python 3.11+**, `asyncio` throughout; never block the ingest path
- **Units:** radians and m/s internally; degrees only for display/export
- **All timestamps** must be timezone-aware UTC `datetime` objects
- **Type hints** required on all functions and dataclasses
- **Logging** via the standard `logging` module (level configurable in `Config.log_level`)
- **No MQTT**, no other-vessel data, no direct `environment.wave.*` dependency
- Use **bounded queues** (`delta_queue_maxsize=1000`, `sample_queue_maxsize=500`)
- Use **fixed-length rolling buffers**; never keep full history in RAM
- Batch Parquet writes (`parquet_batch_size=200` rows)
- All config comes from `Config` (defined in `src/config.py`); the module-level `DEFAULT_CONFIG` is used by callers that don't supply an explicit instance

---

## Running the application

```bash
# Live mode (default) – connects to Signal K server
python src/main.py
python src/main.py live --plots
python src/main.py live --url http://192.168.1.100:3000

# Inspect mode – discovers available self paths, writes path_inventory.md
python src/main.py inspect --duration 120

# Replay mode – replays raw_self_deltas.jsonl offline
python src/main.py replay --input output/20240601_120000/raw_self_deltas.jsonl --plots
```

---

## Running tests

```bash
pip install pytest
pytest tests/ -v
```

All tests live under `tests/`. `conftest.py` at the project root adds `src/` to `sys.path` automatically.

---

## Output files

All outputs go to `~/.sea_state_analyzer/output/YYYYMMDD_HHMMSS/` (default) or the path set by `SEA_STATE_OUTPUT_DIR`:

| File | Description |
|------|-------------|
| `raw_self_deltas.jsonl` | Raw Signal K delta messages |
| `samples.parquet` | Normalized `InstantSample` at 2 Hz with `age_*` / `valid_*` metadata |
| `features_10s.parquet` | 10-second rolling window features |
| `features_30s.parquet` | 30-second rolling window features |
| `features_60s.parquet` | 60-second rolling window features |
| `features_300s.parquet` | 5-minute rolling window features |
| `events.jsonl` | `MotionEstimate` events every 5 s |
| `path_inventory.md` | Inspect-mode path report |
| `plot_*.png` | Optional matplotlib plots |

---

## Signal K subscription paths (self only)

Motion: `navigation.attitude`, `navigation.attitude.roll/pitch/yaw`, `navigation.rateOfTurn`  
Movement: `navigation.speedOverGround`, `navigation.courseOverGroundTrue`, `navigation.headingTrue`  
Wind: `environment.wind.speedTrue/angleTrueWater/speedApparent/angleApparent`  
Position: `navigation.position`, `navigation.datetime`

---

## Feature extraction layers

- **Layer A** – instantaneous derivatives (roll/pitch/yaw rate & acceleration, heading−COG, wind angles relative to bow, speed-normalised roll/pitch using STW with SOG fallback)
- **Layer B** – rolling-window statistics per window [10s, 30s, 60s, 300s]: mean, std, RMS, peak-to-peak, kurtosis, crest factor, zero-crossing period, Welch PSD dominant frequency/period with confidence, spectral energy by band, spectral entropy, period stability, stw_var, current_drift_mean
- **Layer C** – inferred motion proxies: severity (0–1), regime (calm/moderate/active/heavy), encounter direction (beam_like/head_or_following_like/quartering_like/confused_like), regularity, dominant periods with confidence, comfort proxy (0=uncomfortable, 1=comfortable), severity trend

---

## GPS vs non-GPS sensor strategy

The sea-state feature pipeline minimises GPS dependency because GPS updates are slow (~1 Hz) and introduce latency that corrupts fast wave-motion analysis.

| Feature | Preferred source | Fallback | Rationale |
|---------|-----------------|----------|-----------|
| `roll_normalized`, `pitch_normalized` | **STW** (speed through water, paddle wheel) | SOG (GPS) | STW updates faster, no GPS latency; removes current/leeway effects |
| `heading_minus_cog`, `heading_cog_var` | headingTrue + COG (both OK) | — | Measures navigation/current characteristics (slow-changing), not fast wave motion |
| Doppler correction (`delta_v`) | **STW** | None (skipped if unavailable) | Critical for accurate wave period estimation |
| `stw_var` | STW | — | Rolling variance of speed through water |
| `sog_var` | SOG | — | Kept for navigation/current analysis |
| `current_drift_mean` | `environment.current.drift` | Defaults to 0.0 | Direct from Signal K; sanitised for unavailability |
| Position (lat/lon) | GPS | — | No alternative source exists |

**Key principle:** severity, regime, and comfort proxy computations use only roll_rms, pitch_rms, roll_spectral_energy, and yaw_rate_var — all GPS-free.

---

## Versioning

`VERSION` is defined in `src/config.py` (currently `"0.3.0"`) and is included in every output row (samples parquet, features parquet, events JSONL, raw deltas JSONL) so training pipelines can partition data by software version.

**Bump `VERSION` whenever a change likely affects the data model in a way that needs to be taken into account when training** — e.g. adding, removing, or renaming fields in `InstantSample`, `WindowFeatures`, or `MotionEstimate`; changing the scale or meaning of an existing field (like inverting comfort proxy); or altering how features are derived. This ensures training pipelines can partition or filter data by the version that produced it.

---

## Important constraints

- Keep the project portable: macOS first, Raspberry Pi 5 Linux with minimal change
- Do not add deep learning in the first version; heuristic → clustering → supervised is the roadmap
- Reconnect backoff delays: 1 s, 2 s, 5 s, 10 s, 30 s max
- Never crash on malformed messages or missing fields
- Wrap angle derivatives with unwrapping before differentiation
