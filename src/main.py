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
from recorder import Recorder
from signalk_client import InspectClient, SignalKClient
from state_store import SelfStateStore

logger = logging.getLogger(__name__)


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

    async def _sample_loop() -> None:
        """Produce InstantSamples at the configured rate."""
        nonlocal samples_produced, last_sample, last_me, last_wf_short
        interval = 1.0 / config.sample_rate_hz
        while True:
            await asyncio.sleep(interval)
            sample = store.snapshot()
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

    # Run all tasks concurrently
    tasks = [
        asyncio.create_task(client.run(delta_queue), name="signalk_client"),
        asyncio.create_task(_ingest_loop(), name="ingest"),
        asyncio.create_task(_sample_loop(), name="sampler"),
        asyncio.create_task(_console_loop(), name="console"),
        asyncio.create_task(_plot_loop(), name="plotter"),
        asyncio.create_task(_flush_loop(), name="flusher"),
    ]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for t in tasks:
            t.cancel()
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

    config = Config()
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
