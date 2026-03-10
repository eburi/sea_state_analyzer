

# Implementation instructions for Claude: Python wave learner prototype for Signal K vessel self data

Build a **Python 3.11+** application that runs on a MacBook and connects to the local Signal K server at:

`http://primrose.local:3000`

The goal is to analyze **vessel self data only**. Do not use MQTT. Do not assume any useful wave or wind information exists for other vessels. This prototype should subscribe only to the local vessel’s own Signal K data, normalize it, derive motion features, and determine what wave-related motion proxies can be inferred from the onboard sensors currently available.

The first implementation is **not** about producing a final machine-learning model. It is about:

1. ingesting realtime vessel self data from Signal K,
2. normalizing and timestamping it,
3. extracting useful motion and sea-state proxy features,
4. visualizing and recording them,
5. determining what can realistically be inferred from the available onboard sensors,
6. creating a clean dataset for later replay, analysis, clustering, and learning.

---

## 1. Technical direction

Use **Python**.

Implement with:

* `asyncio`
* `websockets` or `aiohttp`
* `httpx` or `aiohttp` for HTTP checks
* `dataclasses` or `pydantic`
* `numpy`
* `scipy`
* `pandas`
* `pyarrow` for Parquet
* `matplotlib`
* optionally `scikit-learn` for later clustering experiments

Keep the code modular so signal-processing code could later be optimized or replaced without redesigning the system.

Do not overbuild a framework.

---

## 2. Required architecture

Implement these modules.

### `config.py`

Contains:

* Signal K base URL
* WebSocket URL
* reconnect settings
* subscription paths
* rolling window sizes
* output directories
* feature extraction parameters
* plotting toggles
* logging level
* vessel self context

Defaults:

* base URL: `http://primrose.local:3000`
* ws URL: `ws://primrose.local:3000/signalk/v1/stream?subscribe=none`

The code should explicitly operate on **vessel self only**.

---

### `signalk_client.py`

Responsibilities:

* connect to the Signal K WebSocket
* receive hello and delta messages
* send explicit subscriptions
* reconnect automatically
* parse only relevant vessel self updates
* push normalized update events into an async queue

Use the Signal K stream endpoint and explicit subscriptions. Start with `subscribe=none` and then subscribe only to required self paths.

---

### `paths.py`

Contains canonical Signal K paths and aliases for **self data only**.

Start by supporting these if present:

* `navigation.speedOverGround`
* `navigation.courseOverGroundTrue`
* `navigation.headingTrue`
* `navigation.headingMagnetic`
* `navigation.rateOfTurn`
* `navigation.attitude`
* `navigation.attitude.roll`
* `navigation.attitude.pitch`
* `navigation.attitude.yaw`
* `navigation.position`
* `navigation.datetime`
* `environment.wind.speedTrue`
* `environment.wind.angleTrueWater`
* `environment.wind.speedApparent`
* `environment.wind.angleApparent`

Do not include `environment.wave.*` in the design assumptions. If such data exists locally on self it may be logged, but the project must not depend on it.

Do not subscribe to or model other vessels.

---

### `models.py`

Define typed structures:

* `RawDeltaMessage`
* `SignalKValueUpdate`
* `InstantSample`
* `WindowFeatures`
* `MotionEstimate`
* `SystemStatus`

`InstantSample` should represent one merged self-state snapshot at one timestamp.

---

### `state_store.py`

Responsibilities:

* maintain latest-known values for vessel self paths
* merge incoming deltas into a single self-state
* track source and timestamp metadata if present
* track age/freshness of each field
* expose a snapshot method

Do not assume every delta message contains a full vessel state.

---

### `feature_extractor.py`

Consumes self-state snapshots and produces:

* instantaneous derived motion metrics
* rolling-window motion features
* wave-related motion proxies inferred from vessel response

---

### `recorder.py`

Writes:

* raw self deltas to JSONL
* normalized self samples to Parquet
* rolling feature windows to Parquet

---

### `plotter.py`

Produces:

* live terminal summaries
* optional rolling plots
* offline analysis plots

---

### `main.py`

Runs the pipeline:

* Signal K client
* async queue
* self state store
* resampler
* feature extractor
* recorder
* plotter

---

## 3. Signal K connection behavior

Before opening the WebSocket, optionally test server availability with:

* `GET /signalk`
  or
* `GET /signalk/v1/api/`

Then connect to:

`ws://primrose.local:3000/signalk/v1/stream?subscribe=none`

On connect:

1. receive and log the hello message,
2. send explicit subscriptions for required self paths,
3. consume delta messages,
4. ignore irrelevant data,
5. continue operating through disconnects.

Implement reconnect backoff:

* 1s
* 2s
* 5s
* 10s
* 30s max

Do not crash on malformed messages or missing fields.

---

## 4. First-pass subscriptions

Subscribe only to the vessel self signals needed for motion inference.

### Motion / attitude

* `navigation.attitude`
* `navigation.attitude.roll`
* `navigation.attitude.pitch`
* `navigation.attitude.yaw`
* `navigation.rateOfTurn`

### Vessel movement

* `navigation.speedOverGround`
* `navigation.courseOverGroundTrue`
* `navigation.headingTrue`

### Wind on self

* `environment.wind.speedTrue`
* `environment.wind.angleTrueWater`
* `environment.wind.speedApparent`
* `environment.wind.angleApparent`

### Position / time

* `navigation.position`
* `navigation.datetime`

If the exact paths differ on this installation, implement an inspection mode that inventories observed **self** paths and recommends substitutes.

---

## 5. Data normalization requirements

The core requirement is a clean canonical **vessel self state**.

For each received value:

* convert timestamps to timezone-aware UTC datetimes
* preserve source timestamps if present
* preserve source identifiers if available
* document any unit assumptions
* ignore or flag stale values beyond configurable age thresholds

Use:

* radians internally for angles
* m/s internally for speeds
* seconds for time
* degrees only for display/export when useful

Create one canonical `InstantSample` at a fixed rate:

* start with **2 Hz**

Do not wait for all sensors to update at the same instant. Use latest-known-value resampling with freshness metadata.

Each sample should include:

* timestamp
* roll
* pitch
* yaw
* speed over ground
* heading
* course over ground
* true wind speed
* true wind angle
* apparent wind speed
* apparent wind angle
* position if available
* signal age per field
* validity mask per field

This validity/freshness metadata is required for later learning and confidence scoring.

---

## 6. What to extract from vessel self data

The available self data can support useful **motion-based wave inference**, but only indirectly through boat response.

Claude should implement feature extraction in three layers.

---

## Layer A: instantaneous derived values

From self-state signals compute:

* roll rate = d(roll)/dt
* pitch rate = d(pitch)/dt
* yaw rate = d(yaw)/dt if needed
* roll acceleration
* pitch acceleration
* yaw acceleration
* heading minus COG
* true wind angle relative to bow
* apparent wind angle relative to bow
* speed-normalized roll and pitch metrics

Important:

* unwrap angles before derivative calculation
* smooth derivatives with configurable light filtering
* avoid adding excessive lag

---

## Layer B: rolling-window motion statistics

Use windows of:

* 10 s
* 30 s
* 60 s
* 5 min

For each window compute:

* mean roll
* mean pitch
* standard deviation of roll
* standard deviation of pitch
* RMS roll
* RMS pitch
* peak-to-peak roll
* peak-to-peak pitch
* roll zero-crossing period
* pitch zero-crossing period
* dominant roll frequency using FFT or Welch PSD
* dominant pitch frequency using FFT or Welch PSD
* spectral energy in configurable frequency bands
* roll/pitch crest factor
* roll/pitch kurtosis
* yaw-rate variance
* SOG variance
* heading-COG variance
* wind-speed variance
* wind-angle variance
* spectral entropy
* stability of dominant period across adjacent windows

These are the main candidate motion-state features.

---

## Layer C: inferred wave-motion proxies

From vessel self motion patterns estimate:

* dominant encounter period
* whether motion is more roll-dominant or pitch-dominant
* probable beam-like / head-following-like / quartering-like encounter tendency
* motion severity index
* motion regularity vs confusion
* comfort proxy
* downwind oscillation or surfing tendency proxy
* autopilot correction proxy if yaw/heading behavior suggests repetitive steering action

These outputs must be described as **inferred motion proxies**, not direct measurements of sea state.

---

## 7. Wave-analysis logic to implement first

Do not try to infer actual wave height as a primary target.

Focus first on these tasks.

### A. Detect motion regime

Estimate whether vessel motion is:

* calm
* moderate
* active
* heavy

Use a heuristic score combining:

* roll RMS
* pitch RMS
* roll spectral energy
* pitch spectral energy
* yaw-rate variance

---

### B. Estimate dominant motion period

Use:

* zero-crossing estimates
* Welch PSD dominant peaks
* confidence score based on agreement and spectral sharpness

Return separate roll and pitch period estimates, and optionally a combined encounter period estimate.

---

### C. Estimate encounter-direction proxy

Infer from:

* roll energy vs pitch energy
* yaw-rate behavior
* true/apparent wind angle relative to bow
* heading stability vs COG stability

Heuristic examples:

* strong roll with weaker pitch -> beam-like tendency
* strong pitch with weaker roll -> head/following-like tendency
* strong roll plus yaw variance with aft-quarter wind angle -> quartering/following tendency
* multiple competing peaks and unstable ratios -> confused or mixed motion

---

### D. Estimate regular vs confused motion

Use:

* number of meaningful spectral peaks
* spectral entropy
* instability in dominant period
* inconsistency of roll/pitch relationship over time

---

### E. Estimate trend over time

Compare short and longer windows:

* improving
* worsening
* stable

Use comparisons across:

* 5 min
* 15 min
* 30 min if enough data exists

---

## 8. What the system should output

The application should continuously produce:

### Console output every 5 to 10 seconds

Include:

* connection state
* sample rate
* freshness state
* roll RMS
* pitch RMS
* dominant roll period
* dominant pitch period
* motion severity score
* motion regularity/confusion estimate
* inferred encounter-direction proxy
* confidence

---

### Files

Write to a dated output directory:

* `raw_self_deltas.jsonl`
* `samples.parquet`
* `features_10s.parquet`
* `features_30s.parquet`
* `features_60s.parquet`
* `events.jsonl`

---

### Optional plots

Generate periodically:

* roll/pitch time series
* heading and COG comparison
* roll PSD
* pitch PSD
* motion severity over time
* dominant motion period over time
* roll RMS vs apparent wind angle
* pitch RMS vs speed over ground

---

## 9. Required self inspection mode

Add:

`python main.py inspect`

This mode should:

* connect to Signal K
* observe only vessel self data
* log all observed self paths and update frequencies
* summarize which self paths are present
* identify substitutes for expected missing paths
* write a report `path_inventory.md`

The report should include:

* path name
* count
* first seen / last seen
* sample values
* source identifiers if available
* whether the path should be used in normal mode

This mode is important because actual onboard path availability may differ from expected names.

---

## 10. Required replay mode

Add:

`python main.py replay --input raw_self_deltas.jsonl`

This mode should:

* replay recorded self deltas
* rebuild canonical self samples
* rerun feature extraction
* regenerate outputs offline

This is required so algorithm work can continue without a live Signal K connection.

---

## 11. Learning-related instructions

Do not start with deep learning.

Implement these stages.

### Stage 1: heuristic estimator

Use only engineered features and thresholds.

### Stage 2: unsupervised clustering

Use rolling-window features and test:

* KMeans
* Gaussian mixture
* HDBSCAN if available

Goal:
discover natural motion regimes such as:

* calm
* regular swell response
* confused motion
* strong quartering/downwind oscillation

### Stage 3: weak supervision

Prepare for later manual labels such as:

* calm
* moderate
* rough
* confused
* surfing
* beam-like
* following-like

Then support simple supervised models later:

* random forest
* gradient boosting
* lightweight online classifier

The first version only needs to prepare a clean feature matrix and exports.

---

## 12. Implementation constraints

Claude must follow these constraints:

* keep realtime I/O async
* avoid blocking the ingest path
* use bounded queues
* batch disk writes
* prevent long-run memory growth
* do not keep full history in RAM
* use fixed-length rolling buffers
* all timestamps must be timezone-aware UTC
* every exported row must include validity/freshness metadata
* reconnect cleanly after failure
* code must run on macOS first and later on Raspberry Pi 5 Linux with minimal change

---

## 13. Initial heuristics to implement

Implement a simple motion severity score from 0 to 1 using:

* roll RMS
* pitch RMS
* roll spectral energy
* yaw-rate variance

Suggested method:

* normalize each metric against configurable ranges
* clip each to `[0, 1]`
* combine with weights
* apply exponential smoothing to the final score

Implement a dominant motion period estimate:

* compute roll dominant period
* compute pitch dominant period
* assign confidence per estimate
* optionally produce a combined encounter period estimate

Implement a motion-direction proxy:

* `beam_like` if roll strongly dominates pitch
* `head_or_following_like` if pitch strongly dominates roll
* `quartering_like` if roll is high and yaw variance is also high
* `confused_like` if multiple peaks and unstable classification

Add confidence scoring:

* low confidence when data is missing or stale
* low confidence when spectra are flat or unstable
* higher confidence when multiple windows agree

---

## 14. Deliverables expected from Claude

Claude should produce:

### A. Codebase

A runnable Python project with:

* `requirements.txt` or `pyproject.toml`
* all modules listed above
* type hints
* logging
* README

### B. README

Include:

* setup instructions
* inspect mode usage
* live mode usage
* replay mode usage
* output file descriptions
* assumptions
* limitations

### C. Example config

Provide a config file with the Primrose defaults.

### D. Minimal tests

At least tests for:

* delta parsing
* self path filtering
* angle unwrapping
* derivative calculation
* PSD extraction
* rolling-window behavior

---

## 15. Suggested development order

Implement in this order:

1. connect to Signal K and print self deltas
2. add explicit self subscriptions
3. add self path inspection mode
4. merge deltas into canonical self state
5. resample into fixed-rate samples
6. record raw and normalized outputs
7. add rolling feature extraction
8. add PSD and period estimation
9. add motion severity and direction heuristics
10. add replay mode
11. add plots
12. add clustering experiments

---

## 16. Important domain cautions

Claude should explicitly document:

* this system infers **boat motion response**, not direct wave truth
* sail trim, point of sail, hull form, autopilot behavior, displacement, and loading affect motion response
* downwind-only or passage-biased data will bias learned motion regimes
* actual wave height, wavelength, and wave direction are not directly observable from these self signals alone without stronger assumptions
* outputs must be described as:

  * inferred motion state
  * inferred encounter characteristics
  * motion-derived sea-state proxies

Do not describe outputs as authoritative environmental wave measurements.

---

## 17. Final instruction to Claude

Implement a clean, modular, practical first version that is immediately useful onboard.

Do not optimize prematurely.
Do not introduce MQTT.
Do not include other vessels.
Do not depend on direct wave sensor data.

Prioritize:

* reliable realtime ingestion of vessel self data,
* correct time alignment,
* high-quality motion feature engineering,
* clear logging,
* replayability,
* exportable datasets.

The best outcome of this first version is a tool that tells us:

* which vessel self paths are actually available,
* how stable and useful they are,
* which motion features are strongest,
* and what wave-related motion proxies can already be inferred from onboard self data alone.

