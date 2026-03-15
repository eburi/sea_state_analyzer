"""Main entry point for the Signal K wave-motion learner prototype.

Usage:
  python main.py              # live mode (default)
  python main.py live         # live mode (explicit)
  python main.py inspect      # path inspection mode
  python main.py replay --input <path/to/raw_self_deltas.jsonl>

All mode documentation is in README.md.

IMPORTANT DOMAIN NOTE:
  This tool infers vessel motion response to sea state.  It does NOT produce
  direct measurements of wave height, period, or direction.  Sail trim,
  point of sail, hull form, autopilot behaviour, displacement, and loading
  all modulate the observed motion.  Outputs must be treated as inferred
  motion proxies, not authoritative environmental measurements.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional

from config import Config, DEFAULT_CONFIG
from feature_extractor import FeatureExtractor
from models import (
    InstantSample,
    MotionEstimate,
    RawDeltaMessage,
    SignalKValueUpdate,
    SystemStatus,
    WindowFeatures,
)
from plotter import FilePlotter, TerminalPlotter
from paths import WAVE_PATH_META
from recorder import Recorder
from signalk_client import InspectClient, SignalKClient
from state_store import SelfStateStore

# Try importing publisher
try:
    from signalk_publisher import build_delta_message, build_meta_delta
    _PUBLISHER_AVAILABLE = True
except ImportError:
    _PUBLISHER_AVAILABLE = False

# Try importing auth module
try:
    from signalk_auth import ensure_auth_token
    _AUTH_AVAILABLE = True
except ImportError:
    _AUTH_AVAILABLE = False

logger = logging.getLogger(__name__)

# Try importing IMU reader — absent on Mac / without smbus2
try:
    from imu_reader import IMUReader, IMUSample
    _IMU_AVAILABLE = True
except ImportError:
    _IMU_AVAILABLE = False

    class _IMUReaderStub:  # type: ignore[no-redef]
        """Placeholder so attribute access doesn't crash at type-check time."""
        @staticmethod
        async def create(**kwargs: object) -> None:
            return None

    IMUReader = _IMUReaderStub  # type: ignore[misc,assignment]
    IMUSample = None  # type: ignore[misc,assignment]


# --------------------------------------------------------------------------- #
# Shared pipeline helpers                                                      #
# --------------------------------------------------------------------------- #

def _setup_logging(level: int) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# LIVE MODE                                                                    #
# --------------------------------------------------------------------------- #

async def _live_mode(config: Config) -> None:
    """
    Connect to Signal K, ingest vessel self data, extract features,
    record outputs, and print console summaries.

    When IMU hardware is available, reads accelerometer/gyroscope at
    imu_sample_rate_hz and merges the latest reading into each
    InstantSample.
    """
    output_dir = config.dated_output_dir()
    logger.info("Output directory: %s", output_dir)

    client = SignalKClient(config)
    store = SelfStateStore(config)
    extractor = FeatureExtractor(config)
    recorder = Recorder(output_dir, config)
    term_plotter = TerminalPlotter(config)
    file_plotter = FilePlotter(output_dir, config)

    recorder.open()

    # Check server availability (non-blocking; failure does not abort)
    await client.check_availability()

    # --- Auth setup (concurrent — does not block other tasks) ------------- #
    # The auth_ready event is set once a valid token is obtained (or auth
    # is skipped).  The _publish_loop waits on this event before sending.
    # auth_failed is set if auth could not be obtained, so _publish_loop
    # can exit gracefully instead of waiting forever.
    auth_ready = asyncio.Event()
    auth_failed = asyncio.Event()

    if not (config.publish_to_signalk and _PUBLISHER_AVAILABLE and _AUTH_AVAILABLE):
        # Publishing not configured or deps missing — nothing to wait for
        if config.publish_to_signalk and not _AUTH_AVAILABLE:
            logger.warning("publish_to_signalk=True but signalk_auth module not available")
        auth_ready.set()  # unblock publish_loop (it will still check _PUBLISHER_AVAILABLE)

    async def _auth_task() -> None:
        """Obtain Signal K auth token concurrently with other startup tasks.

        Sets auth_ready on success, auth_failed on failure.  The
        _publish_loop waits on auth_ready before attempting sends.

        After obtaining the token, forces a WebSocket reconnect so the
        new connection includes the Authorization header.
        """
        if not (config.publish_to_signalk and _PUBLISHER_AVAILABLE and _AUTH_AVAILABLE):
            return
        logger.info("Authenticating for Signal K write access (runs in background)…")
        try:
            auth = await ensure_auth_token(config)
            if auth and auth.token:
                client.set_auth_token(auth.token)
                logger.info("Authenticated — forcing reconnect for authenticated WebSocket")
                await client.reconnect()
                auth_ready.set()
            else:
                logger.warning(
                    "Could not obtain auth token — publishing disabled. "
                    "Approve the device request in Signal K admin UI and restart."
                )
                auth_failed.set()
        except Exception as exc:
            logger.error("Auth task failed: %s — publishing disabled", exc)
            auth_failed.set()

    # --- IMU setup (best-effort) ----------------------------------------- #
    imu_reader: Optional["IMUReader"] = None  # type: ignore[name-defined]
    # Latest IMU reading, shared between _imu_loop and _sample_loop.
    # Written by _imu_loop at imu_sample_rate_hz, read by _sample_loop at
    # sample_rate_hz.  No lock needed: single writer, single reader, and a
    # stale-by-one-sample race is harmless.
    latest_imu_sample: Optional["IMUSample"] = None  # type: ignore[name-defined]

    if config.imu_enabled and _IMU_AVAILABLE:
        logger.info("Attempting IMU init on i2c bus %d (auto_detect=%s, fallback_addr=0x%02X)…",
                     config.imu_bus_number, config.imu_auto_detect, config.imu_address)
        imu_reader = await IMUReader.create(
            bus_number=config.imu_bus_number,
            address=config.imu_address,
            auto_detect=config.imu_auto_detect,
        )
        if imu_reader is not None:
            logger.info("IMU reader active (%s) – sampling at %.0f Hz",
                        imu_reader.chip_name, config.imu_sample_rate_hz)
        else:
            logger.info("IMU not available – continuing without accelerometer data")
    elif not _IMU_AVAILABLE:
        logger.info("smbus2 not installed – IMU support disabled")
    else:
        logger.info("IMU disabled in config")

    delta_queue: asyncio.Queue[SignalKValueUpdate] = asyncio.Queue(
        maxsize=config.delta_queue_maxsize
    )

    start_time = time.monotonic()
    samples_produced = 0

    # History buffers for offline plots (bounded)
    plot_sample_buf: Deque[InstantSample] = deque(maxlen=int(30 * 60 * config.sample_rate_hz))
    plot_estimate_buf: Deque[MotionEstimate] = deque(maxlen=int(30 * 60 / 5))
    last_sample: Optional[InstantSample] = None
    last_me: Optional[MotionEstimate] = None
    last_wf_short: Optional[WindowFeatures] = None

    async def _ingest_loop() -> None:
        """Apply incoming value updates to the state store."""
        while True:
            update: SignalKValueUpdate = await delta_queue.get()
            await store.apply_update(update)
            delta_queue.task_done()

    async def _imu_loop() -> None:
        """Poll IMU at imu_sample_rate_hz, store latest reading.

        Runs only when imu_reader is not None.  Errors are logged but
        never crash the loop — a single bad read is skipped.

        Also feeds vertical_accel to the feature extractor's Kalman
        heave filter at the full IMU rate.
        """
        nonlocal latest_imu_sample
        assert imu_reader is not None
        interval = 1.0 / config.imu_sample_rate_hz
        consecutive_errors = 0
        while True:
            try:
                if config.imu_include_mag:
                    latest_imu_sample = await imu_reader.read_sample()
                else:
                    latest_imu_sample = await imu_reader.read_accel_gyro_only()
                consecutive_errors = 0
                # Feed vertical accel to feature extractor for wave estimation
                if latest_imu_sample is not None and latest_imu_sample.vertical_accel is not None:
                    extractor.add_imu_accel(latest_imu_sample.vertical_accel)
            except Exception as exc:
                consecutive_errors += 1
                if consecutive_errors <= 3 or consecutive_errors % 100 == 0:
                    logger.warning("IMU read error (#%d): %s", consecutive_errors, exc)
            await asyncio.sleep(interval)

    def _merge_imu(sample: InstantSample) -> InstantSample:
        """Overlay latest IMU data onto an InstantSample (in-place mutation)."""
        imu = latest_imu_sample
        if imu is None:
            return sample
        sample.accel_x = imu.accel_x
        sample.accel_y = imu.accel_y
        sample.accel_z = imu.accel_z
        sample.gyro_x = imu.gyro_x
        sample.gyro_y = imu.gyro_y
        sample.gyro_z = imu.gyro_z
        sample.mag_x = imu.mag_x
        sample.mag_y = imu.mag_y
        sample.mag_z = imu.mag_z
        sample.vertical_accel = imu.vertical_accel
        # Track IMU freshness
        imu_age = (sample.timestamp - imu.timestamp).total_seconds()
        sample.field_ages["imu"] = imu_age
        sample.field_valid["imu"] = imu_age < config.stale_threshold_s
        return sample

    async def _sample_loop() -> None:
        """Produce InstantSamples at the configured rate."""
        nonlocal samples_produced, last_sample, last_me, last_wf_short
        interval = 1.0 / config.sample_rate_hz
        while True:
            await asyncio.sleep(interval)
            sample = store.snapshot()

            # Merge latest IMU reading (if available)
            _merge_imu(sample)

            last_sample = sample
            samples_produced += 1

            # Feature extraction
            extractor.add_sample(sample)

            # Record
            recorder.record_sample(sample)
            plot_sample_buf.append(sample)

            # Window features – compute and record at approx 1 Hz
            if samples_produced % max(1, int(config.sample_rate_hz)) == 0:
                for w in config.rolling_windows_s:
                    wf = extractor.get_window_features(w)
                    if wf is not None:
                        recorder.record_window_features(wf)
                        if w == config.rolling_windows_s[0]:
                            last_wf_short = wf

            # Motion estimate every 5 s
            if samples_produced % max(1, int(config.sample_rate_hz * 5)) == 0:
                me = extractor.get_motion_estimate(
                    window_s=config.rolling_windows_s[min(2, len(config.rolling_windows_s) - 1)],
                    short_window_s=config.rolling_windows_s[0],
                )
                if me is not None:
                    last_me = me
                    recorder.record_motion_estimate(me)
                    plot_estimate_buf.append(me)

    async def _console_loop() -> None:
        """Print terminal summary at the configured interval."""
        nonlocal last_sample, last_me, last_wf_short
        while True:
            await asyncio.sleep(config.console_interval_s)
            uptime = time.monotonic() - start_time
            status = SystemStatus(
                timestamp=_now_utc(),
                connected=client.connected,
                ws_url=config.ws_url,
                samples_produced=samples_produced,
                sample_rate_hz=config.sample_rate_hz,
                fields_fresh=last_sample.field_valid if last_sample else {},
                uptime_s=uptime,
                last_delta_at=client.last_delta_at,
                reconnect_count=client.reconnect_count,
            )
            term_plotter.print_summary(status, last_sample, last_wf_short, last_me)

    async def _plot_loop() -> None:
        """Generate file plots at the configured interval."""
        if not config.enable_live_plots:
            return
        while True:
            await asyncio.sleep(config.plot_interval_s)
            try:
                file_plotter.plot_all(
                    list(plot_sample_buf),
                    {},
                    list(plot_estimate_buf),
                )
            except Exception as exc:
                logger.warning("Plot error: %s", exc)

    async def _flush_loop() -> None:
        """Periodic force-flush of recorder batches."""
        while True:
            await asyncio.sleep(30.0)
            recorder.flush_all()

    async def _validate_publish(cfg: Config, sk_client: SignalKClient) -> bool:
        """Check that published wave data appears in Signal K's data model.

        Queries the REST API for the motionSeverity path.  If the path
        exists with a recent value, publishing is confirmed working.
        """
        try:
            import httpx as _httpx
            url = f"{cfg.base_url}/signalk/v1/api/vessels/self/environment/water/waves"
            headers: Dict[str, str] = {}
            if sk_client._auth_token:
                headers["Authorization"] = f"Bearer {sk_client._auth_token}"
            async with _httpx.AsyncClient(timeout=5.0) as hc:
                resp = await hc.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    if data and isinstance(data, dict):
                        logger.info(
                            "Publish validation OK — wave data visible in Signal K "
                            "(paths: %s)",
                            ", ".join(sorted(data.keys())[:5]),
                        )
                        return True
                logger.warning(
                    "Publish validation: wave data not yet visible (HTTP %d). "
                    "This may indicate the server is ignoring writes.",
                    resp.status_code,
                )
                return False
        except Exception as exc:
            logger.warning("Publish validation error: %s", exc)
            return False

    async def _publish_loop() -> None:
        """Publish latest MotionEstimate to Signal K via authenticated WebSocket.

        Waits for the auth_ready event before starting, so authentication
        can complete concurrently with ingestion / sampling / display.

        Sends delta messages through the SignalKClient's WebSocket connection.
        Requires a valid auth token to be set on the client (see signalk_auth).
        Skips silently when no estimate is available or not connected.

        After the first successful send, validates that the data appears in
        the Signal K data model via REST API (echo-back check).
        """
        # Wait for auth to complete (or fail) before publishing
        logger.info("Publish loop waiting for authentication…")
        done, _ = await asyncio.wait(
            [
                asyncio.create_task(auth_ready.wait()),
                asyncio.create_task(auth_failed.wait()),
            ],
            return_when=asyncio.FIRST_COMPLETED,
        )
        if auth_failed.is_set() and not auth_ready.is_set():
            logger.warning("Publish loop exiting — authentication failed")
            return
        logger.info("Publish loop: auth ready, starting delta publishing")

        # Send metadata delta once so Signal K has units/descriptions
        try:
            meta_msg = build_meta_delta(self_context=client.self_context)
            meta_ok = await client.send(meta_msg)
            if meta_ok:
                logger.info(
                    "Published wave path metadata (%d bytes, %d paths)",
                    len(meta_msg), len(WAVE_PATH_META),
                )
            else:
                logger.warning("Failed to send wave path metadata (not connected?)")
        except Exception as exc:
            logger.warning("Error sending wave path metadata: %s", exc)

        publish_count = 0
        fail_count = 0
        validated = False
        while True:
            await asyncio.sleep(config.publish_interval_s)
            me = last_me
            if me is None:
                continue
            msg = build_delta_message(
                me,
                self_context=client.self_context,
                source_label=config.publish_source_label,
            )
            if msg is None:
                continue

            ok = await client.send(msg)
            if ok:
                publish_count += 1
                if publish_count <= 3 or publish_count % 100 == 0:
                    logger.info(
                        "Published wave delta #%d via WS (%d bytes)",
                        publish_count, len(msg),
                    )

                # Echo-back validation on the 2nd successful publish
                if publish_count == 2 and not validated:
                    validated = await _validate_publish(config, client)
            else:
                fail_count += 1
                if fail_count <= 3 or fail_count % 100 == 0:
                    logger.warning("Publish failed #%d", fail_count)

    # Run all tasks concurrently
    tasks = [
        asyncio.create_task(client.run(delta_queue), name="signalk_client"),
        asyncio.create_task(_ingest_loop(), name="ingest"),
        asyncio.create_task(_sample_loop(), name="sampler"),
        asyncio.create_task(_console_loop(), name="console"),
        asyncio.create_task(_plot_loop(), name="plotter"),
        asyncio.create_task(_flush_loop(), name="flusher"),
    ]
    if imu_reader is not None:
        tasks.append(asyncio.create_task(_imu_loop(), name="imu"))
    # Auth runs concurrently — does not block other tasks
    if config.publish_to_signalk and _PUBLISHER_AVAILABLE and _AUTH_AVAILABLE:
        tasks.append(asyncio.create_task(_auth_task(), name="auth"))
    if config.publish_to_signalk and _PUBLISHER_AVAILABLE:
        tasks.append(asyncio.create_task(_publish_loop(), name="publisher"))
        logger.info(
            "Signal K publishing enabled (every %.0fs, authenticated WebSocket)",
            config.publish_interval_s,
        )
    elif config.publish_to_signalk and not _PUBLISHER_AVAILABLE:
        logger.warning("publish_to_signalk=True but signalk_publisher module not available")
    else:
        logger.info("Signal K publishing disabled in config")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for t in tasks:
            t.cancel()
        if imu_reader is not None:
            imu_reader.close()
        recorder.close()
        if config.enable_live_plots:
            file_plotter.plot_all(
                list(plot_sample_buf), {}, list(plot_estimate_buf)
            )
        logger.info("Shutdown complete")


# --------------------------------------------------------------------------- #
# INSPECT MODE                                                                 #
# --------------------------------------------------------------------------- #

async def _inspect_mode(config: Config, duration_s: Optional[float] = None) -> None:
    """
    Connect to Signal K, observe all vessel self paths, and write a report.
    """
    if duration_s is None:
        duration_s = config.inspect_duration_s

    logger.info("Inspect mode: observing self paths for %.0fs…", duration_s)

    output_dir = config.dated_output_dir()
    client = InspectClient(config)
    await client.check_availability()

    delta_queue: asyncio.Queue[SignalKValueUpdate] = asyncio.Queue(maxsize=5000)

    # Path inventory: {path: {count, first_seen, last_seen, sources, sample_values}}
    inventory: Dict[str, dict] = {}

    async def _observe() -> None:
        while True:
            update: SignalKValueUpdate = await delta_queue.get()
            p = update.path
            now_str = update.received_at.isoformat()
            if p not in inventory:
                inventory[p] = {
                    "count": 0,
                    "first_seen": now_str,
                    "last_seen": now_str,
                    "sources": set(),
                    "sample_values": [],
                }
            entry = inventory[p]
            entry["count"] += 1
            entry["last_seen"] = now_str
            if update.source:
                entry["sources"].add(update.source)
            if len(entry["sample_values"]) < 5:
                entry["sample_values"].append(str(update.value)[:80])
            delta_queue.task_done()

    client_task = asyncio.create_task(client.run_inspect(delta_queue), name="inspect_client")
    observe_task = asyncio.create_task(_observe(), name="observer")

    print(f"\nInspecting Signal K for {duration_s:.0f} seconds…  (Ctrl-C to stop early)\n")
    try:
        await asyncio.wait_for(
            asyncio.gather(client_task, observe_task, return_exceptions=True),
            timeout=duration_s,
        )
    except asyncio.TimeoutError:
        pass
    finally:
        client_task.cancel()
        observe_task.cancel()

    # Write report
    _write_path_inventory(inventory, output_dir)


def _write_path_inventory(inventory: Dict[str, dict], output_dir: Path) -> None:
    from paths import SUBSCRIPTION_PATHS

    report_path = output_dir / "path_inventory.md"

    # Sort by count descending
    sorted_paths = sorted(inventory.items(), key=lambda x: -x[1]["count"])

    lines = [
        "# Signal K Path Inventory",
        "",
        f"*Generated {datetime.now(timezone.utc).isoformat()}*",
        "",
        "## Summary",
        "",
        f"| Stat | Value |",
        f"|------|-------|",
        f"| Total paths observed | {len(inventory)} |",
        f"| Expected paths present | "
        f"{sum(1 for p in SUBSCRIPTION_PATHS if p in inventory)} / {len(SUBSCRIPTION_PATHS)} |",
        "",
        "## Expected paths status",
        "",
        "| Path | Present | Count | Recommended |",
        "|------|---------|-------|-------------|",
    ]

    for p in SUBSCRIPTION_PATHS:
        if p in inventory:
            cnt = inventory[p]["count"]
            lines.append(f"| `{p}` | ✓ | {cnt} | yes |")
        else:
            lines.append(f"| `{p}` | ✗ | 0 | check substitutes |")

    lines += [
        "",
        "## All observed self paths",
        "",
        "| Path | Count | First seen | Last seen | Sources | Sample values |",
        "|------|-------|-----------|-----------|---------|---------------|",
    ]

    for path, info in sorted_paths:
        sources = ", ".join(sorted(info["sources"])) if info["sources"] else "—"
        samples = " / ".join(info["sample_values"][:3])
        in_use = "**yes**" if path in SUBSCRIPTION_PATHS else "no"
        lines.append(
            f"| `{path}` | {info['count']} | {info['first_seen'][:19]} | "
            f"{info['last_seen'][:19]} | {sources} | {samples[:60]} |"
        )

    lines += [
        "",
        "## Notes",
        "",
        "- Paths not listed above are not present in this vessel's Signal K stream.",
        "- If expected paths are missing, check instrument connections on Signal K.",
        "- Navigation.attitude may arrive as a compound object (roll/pitch/yaw together).",
        "",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nPath inventory written to: {report_path}")

    # Also print a summary
    print(f"\n{'─'*60}")
    print(f"Paths observed: {len(inventory)}")
    print(f"Expected paths found: {sum(1 for p in SUBSCRIPTION_PATHS if p in inventory)}/{len(SUBSCRIPTION_PATHS)}")
    print(f"{'─'*60}")
    print(f"{'PATH':<50} {'COUNT':>6}")
    print(f"{'─'*60}")
    for path, info in sorted_paths[:30]:
        marker = "*" if path in SUBSCRIPTION_PATHS else " "
        print(f"{marker} {path:<48} {info['count']:>6}")
    if len(sorted_paths) > 30:
        print(f"  … and {len(sorted_paths) - 30} more paths")
    print(f"{'─'*60}")
    print("  * = expected subscription path")


# --------------------------------------------------------------------------- #
# REPLAY MODE                                                                  #
# --------------------------------------------------------------------------- #

async def _replay_mode(config: Config, input_path: Path) -> None:
    """
    Replay a recorded raw_self_deltas.jsonl file, rebuild samples, and
    re-run feature extraction.
    """
    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        sys.exit(1)

    output_dir = config.dated_output_dir()
    logger.info("Replay mode: reading %s → %s", input_path, output_dir)

    store = SelfStateStore(config)
    extractor = FeatureExtractor(config)
    recorder = Recorder(output_dir, config)
    term_plotter = TerminalPlotter(config)
    file_plotter = FilePlotter(output_dir, config)

    recorder.open()

    samples_produced = 0
    last_me: Optional[MotionEstimate] = None
    plot_samples: List[InstantSample] = []
    plot_estimates: List[MotionEstimate] = []

    frame_interval = 1.0 / config.sample_rate_hz
    last_sample_ts: Optional[datetime] = None

    print(f"\nReplaying {input_path}…\n")

    with open(input_path, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Line %d: JSON parse error, skipping", line_no)
                continue

            received_at_str = obj.get("received_at")
            received_at: datetime
            if received_at_str:
                try:
                    received_at = datetime.fromisoformat(
                        received_at_str.replace("Z", "+00:00")
                    )
                    if received_at.tzinfo is None:
                        received_at = received_at.replace(tzinfo=timezone.utc)
                except ValueError:
                    received_at = _now_utc()
            else:
                received_at = _now_utc()

            raw_msg = obj.get("raw", obj)
            context = obj.get("context", "vessels.self")
            updates = raw_msg.get("updates", [])

            delta = RawDeltaMessage(
                received_at=received_at,
                context=context,
                updates=updates,
                raw=raw_msg,
            )

            # Extract updates
            for update_block in updates:
                if not isinstance(update_block, dict):
                    continue
                from signalk_client import _extract_source_label, _parse_sk_timestamp

                source = _extract_source_label(update_block)
                ts = _parse_sk_timestamp(update_block.get("timestamp"))
                values = update_block.get("values", [])
                for entry in values if isinstance(values, list) else []:
                    if not isinstance(entry, dict):
                        continue
                    path = entry.get("path")
                    value = entry.get("value")
                    if path is None:
                        continue
                    update = SignalKValueUpdate(
                        path=path,
                        value=value,
                        source=source,
                        timestamp=ts,
                        received_at=received_at,
                    )
                    store.apply_update_sync(update)

            # Decide whether to emit a sample based on elapsed time
            if last_sample_ts is None or (
                received_at.timestamp() - last_sample_ts.timestamp() >= frame_interval
            ):
                sample = store.snapshot()
                # Use the delta's timestamp rather than now()
                from dataclasses import replace
                sample = InstantSample(
                    timestamp=received_at,
                    roll=sample.roll,
                    pitch=sample.pitch,
                    yaw=sample.yaw,
                    rate_of_turn=sample.rate_of_turn,
                    sog=sample.sog,
                    cog=sample.cog,
                    heading=sample.heading,
                    wind_speed_true=sample.wind_speed_true,
                    wind_angle_true=sample.wind_angle_true,
                    wind_speed_apparent=sample.wind_speed_apparent,
                    wind_angle_apparent=sample.wind_angle_apparent,
                    latitude=sample.latitude,
                    longitude=sample.longitude,
                    field_ages=sample.field_ages,
                    field_valid=sample.field_valid,
                )
                extractor.add_sample(sample)
                recorder.record_sample(sample)
                plot_samples.append(sample)
                samples_produced += 1
                last_sample_ts = received_at

                if samples_produced % max(1, int(config.sample_rate_hz)) == 0:
                    for w in config.rolling_windows_s:
                        wf = extractor.get_window_features(w)
                        if wf is not None:
                            recorder.record_window_features(wf)

                if samples_produced % max(1, int(config.sample_rate_hz * 5)) == 0:
                    me = extractor.get_motion_estimate(
                        window_s=config.rolling_windows_s[min(2, len(config.rolling_windows_s) - 1)]
                    )
                    if me is not None:
                        last_me = me
                        recorder.record_motion_estimate(me)
                        plot_estimates.append(me)

                if samples_produced % 100 == 0:
                    print(f"\r  Processed {line_no} delta lines → {samples_produced} samples", end="", flush=True)

    print(f"\n  Done. {samples_produced} samples generated.")

    recorder.close()

    if config.enable_live_plots and plot_samples:
        file_plotter.plot_all(plot_samples, {}, plot_estimates)
        print(f"  Plots written to {output_dir}")

    print(f"  Output: {output_dir}")


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Signal K vessel self wave-motion learner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="mode")

    # live (default)
    live_p = sub.add_parser("live", help="Live Signal K ingestion (default)")
    live_p.add_argument("--plots", action="store_true", help="Enable live matplotlib plots")
    live_p.add_argument("--url", default=None, help="Override Signal K base URL")

    # inspect
    insp_p = sub.add_parser("inspect", help="Inspect available Signal K self paths")
    insp_p.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Observation duration in seconds (default: config.inspect_duration_s)",
    )
    insp_p.add_argument("--url", default=None, help="Override Signal K base URL")

    # replay
    rep_p = sub.add_parser("replay", help="Replay a recorded raw_self_deltas.jsonl")
    rep_p.add_argument("--input", required=True, type=Path, help="Input JSONL file")
    rep_p.add_argument("--plots", action="store_true", help="Generate plots after replay")

    return parser


def main() -> None:
    parser = _build_parser()
    args, _ = parser.parse_known_args()

    # Start with env-var overrides (for HA App), then apply CLI args on top
    config = Config.from_env()
    _setup_logging(config.log_level)

    mode = args.mode or "live"

    if hasattr(args, "url") and args.url:
        config.base_url = args.url
        config.ws_url = (
            args.url.replace("http://", "ws://").replace("https://", "wss://")
            + "/signalk/v1/stream?subscribe=none"
        )

    if hasattr(args, "plots") and args.plots:
        config.enable_live_plots = True

    if mode == "live":
        logger.info("Starting live mode → %s", config.ws_url)
        try:
            asyncio.run(_live_mode(config))
        except KeyboardInterrupt:
            print("\nStopped.")

    elif mode == "inspect":
        logger.info("Starting inspect mode → %s", config.base_url)
        try:
            asyncio.run(_inspect_mode(config, duration_s=getattr(args, "duration", None)))
        except KeyboardInterrupt:
            print("\nStopped.")

    elif mode == "replay":
        logger.info("Starting replay mode ← %s", args.input)
        try:
            asyncio.run(_replay_mode(config, input_path=args.input))
        except KeyboardInterrupt:
            print("\nStopped.")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
