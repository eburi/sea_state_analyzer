# Copilot Instructions – boat_state

## Project overview

`boat_state` is a Python 3.11+ prototype that connects to a Signal K marine server (`http://primrose.local:3000`), ingests **vessel self data only**, and derives inferred sea-state motion proxies from onboard attitude, movement, and wind sensors.

> **Domain caution:** All outputs are *inferred motion proxies*, not direct wave measurements. Never describe outputs as authoritative wave height, direction, or period values.

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
  recorder.py          – batched JSONL + Parquet output
  plotter.py           – console summaries + optional matplotlib PNGs
  main.py              – CLI entry point: live / inspect / replay modes
tests/
  test_parsing.py      – delta parsing, self-path filtering, state store
  test_features.py     – angle unwrapping, PSD, spectral features, regime classification
  test_rolling.py      – rolling window statistics and multi-window behaviour
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

All outputs go to `output/YYYYMMDD_HHMMSS/`:

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

- **Layer A** – instantaneous derivatives (roll/pitch/yaw rate & acceleration, heading−COG, wind angles relative to bow, speed-normalised roll/pitch)
- **Layer B** – rolling-window statistics per window [10s, 30s, 60s, 300s]: mean, std, RMS, peak-to-peak, kurtosis, crest factor, zero-crossing period, Welch PSD dominant frequency/period with confidence, spectral energy by band, spectral entropy, period stability
- **Layer C** – inferred motion proxies: severity (0–1), regime (calm/moderate/active/heavy), encounter direction (beam_like/head_or_following_like/quartering_like/confused_like), regularity, dominant periods with confidence, comfort proxy, severity trend

---

## Important constraints

- Keep the project portable: macOS first, Raspberry Pi 5 Linux with minimal change
- Do not add deep learning in the first version; heuristic → clustering → supervised is the roadmap
- Reconnect backoff delays: 1 s, 2 s, 5 s, 10 s, 30 s max
- Never crash on malformed messages or missing fields
- Wrap angle derivatives with unwrapping before differentiation
