"""Signal K WebSocket client.

Connects to the Signal K stream endpoint, receives hello and delta messages,
sends explicit subscriptions for vessel self paths, and pushes normalized
SignalKValueUpdate objects into an asyncio queue.

Reconnection uses exponential back-off as configured.  The client never
raises from its main run-loop; errors are logged and retried.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from config import Config, DEFAULT_CONFIG
from models import RawDeltaMessage, SignalKValueUpdate
from paths import SUBSCRIPTION_PATHS

logger = logging.getLogger(__name__)

# Signal K subscription message period (ms).  We subscribe at a fast rate
# and resample in the pipeline.
_SUBSCRIBE_PERIOD_MS = 200


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_sk_timestamp(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse a Signal K ISO-8601 timestamp string to an aware UTC datetime."""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _build_subscription_message(context: str) -> str:
    """Return a JSON subscription message for all required self paths."""
    subscribe = [
        {
            "path": path,
            "period": _SUBSCRIBE_PERIOD_MS,
            "format": "full",
            "policy": "ideal",
            "minPeriod": 100,
        }
        for path in SUBSCRIPTION_PATHS
    ]
    msg = {"context": context, "subscribe": subscribe}
    return json.dumps(msg)


class SignalKClient:
    """
    Async Signal K WebSocket client.

    Usage::

        client = SignalKClient(config)
        queue = asyncio.Queue(maxsize=config.delta_queue_maxsize)
        asyncio.create_task(client.run(queue))
    """

    def __init__(self, config: Config = DEFAULT_CONFIG) -> None:
        self._config = config
        self._self_context: str = config.vessel_self_context
        self._connected: bool = False
        self._reconnect_count: int = 0
        self._last_delta_at: Optional[datetime] = None
        self._error_count: int = 0
        self._ws: Optional[Any] = None  # active websocket for bidirectional use

    # ------------------------------------------------------------------ #
    # Public                                                                #
    # ------------------------------------------------------------------ #

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    @property
    def last_delta_at(self) -> Optional[datetime]:
        return self._last_delta_at

    @property
    def self_context(self) -> str:
        return self._self_context

    async def send(self, message: str) -> bool:
        """Send a message through the active WebSocket.

        Returns True if sent successfully, False if no connection or error.
        Used by the publisher to send delta messages back to Signal K.
        """
        ws = self._ws
        if ws is None or not self._connected:
            return False
        try:
            await ws.send(message)
            return True
        except Exception as exc:
            logger.debug("send() failed: %s", exc)
            return False

    async def check_availability(self) -> bool:
        """
        Probe the Signal K REST endpoint to verify server reachability.
        Returns True if reachable.
        """
        urls = [
            f"{self._config.base_url}/signalk",
            f"{self._config.base_url}/signalk/v1/api/",
        ]
        async with httpx.AsyncClient(timeout=5.0) as client:
            for url in urls:
                try:
                    resp = await client.get(url)
                    if resp.status_code < 500:
                        logger.info("Signal K server reachable at %s", url)
                        return True
                except Exception as exc:
                    logger.debug("HTTP probe %s failed: %s", url, exc)
        logger.warning("Signal K server not reachable at %s", self._config.base_url)
        return False

    async def run(self, queue: asyncio.Queue) -> None:
        """
        Main run-loop.  Connects, subscribes, consumes deltas, and reconnects
        automatically on failure.  Never returns (runs until task is cancelled).
        """
        delay_index = 0
        delays = self._config.reconnect_delays

        while True:
            try:
                await self._connect_and_stream(queue)
                # If we get here the connection closed cleanly – treat as error
                logger.info("WebSocket closed cleanly, will reconnect")
            except asyncio.CancelledError:
                logger.info("SignalKClient cancelled")
                raise
            except Exception as exc:
                self._error_count += 1
                logger.warning("SignalKClient error: %s", exc)

            self._connected = False
            self._ws = None
            delay = delays[min(delay_index, len(delays) - 1)]
            logger.info(
                "Reconnecting in %.0fs (attempt %d)…",
                delay,
                self._reconnect_count + 1,
            )
            await asyncio.sleep(delay)
            delay_index = min(delay_index + 1, len(delays) - 1)
            self._reconnect_count += 1

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    async def _connect_and_stream(self, queue: asyncio.Queue) -> None:
        logger.info("Connecting to %s", self._config.ws_url)

        async with websockets.connect(
            self._config.ws_url,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=15,
        ) as ws:
            self._ws = ws
            try:
                hello_raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                hello = json.loads(hello_raw)
                logger.info(
                    "Signal K hello: name=%s version=%s self=%s",
                    hello.get("name", "?"),
                    hello.get("version", "?"),
                    hello.get("self", "?"),
                )
                if "self" in hello and hello["self"]:
                    self._self_context = hello["self"]
                    logger.info("Using self context: %s", self._self_context)
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for hello message")
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Could not parse hello: %s", exc)

            # ---- subscribe -------------------------------------------- #
            sub_msg = _build_subscription_message(self._self_context)
            await ws.send(sub_msg)
            logger.info(
                "Subscribed to %d self paths", len(SUBSCRIPTION_PATHS)
            )

            self._connected = True

            # ---- stream ----------------------------------------------- #
            async for raw_msg in ws:
                await self._handle_message(raw_msg, queue)

    async def _handle_message(
        self, raw_msg: str, queue: asyncio.Queue
    ) -> None:
        received_at = _now_utc()
        try:
            msg = json.loads(raw_msg)
        except json.JSONDecodeError:
            logger.debug("Non-JSON message: %s", raw_msg[:120])
            return

        if not isinstance(msg, dict):
            return

        # Filter to self context only
        context = msg.get("context", "")
        if not self._is_self(context):
            return

        updates = msg.get("updates")
        if not updates:
            return

        raw_delta = RawDeltaMessage(
            received_at=received_at,
            context=context,
            updates=updates,
            raw=msg,
        )

        self._last_delta_at = received_at

        # Extract individual path/value updates and push to queue
        for update_block in updates:
            if not isinstance(update_block, dict):
                continue

            source_label = _extract_source_label(update_block)
            ts = _parse_sk_timestamp(update_block.get("timestamp"))

            values = update_block.get("values")
            if not isinstance(values, list):
                continue

            for entry in values:
                if not isinstance(entry, dict):
                    continue
                path = entry.get("path")
                value = entry.get("value")
                if path is None:
                    continue

                update = SignalKValueUpdate(
                    path=path,
                    value=value,
                    source=source_label,
                    timestamp=ts,
                    received_at=received_at,
                )
                try:
                    queue.put_nowait(update)
                except asyncio.QueueFull:
                    # Drop oldest item and retry
                    try:
                        queue.get_nowait()
                        queue.put_nowait(update)
                    except Exception:
                        pass

    def _is_self(self, context: str) -> bool:
        """Return True if the context refers to this vessel."""
        if context == "vessels.self":
            return True
        if context == self._self_context:
            return True
        # Some servers send the full URN as self context
        if (
            self._self_context != self._config.vessel_self_context
            and context == self._self_context
        ):
            return True
        return False


# --------------------------------------------------------------------------- #
# Inspect mode: observe all self paths                                         #
# --------------------------------------------------------------------------- #

class InspectClient(SignalKClient):
    """
    Variant of SignalKClient for path inspection.  Subscribes to all paths
    ('subscribe=all') and records every self path seen with update counts.
    """

    def __init__(self, config: Config = DEFAULT_CONFIG) -> None:
        super().__init__(config)
        self._inspect_ws_url = (
            config.base_url.replace("http://", "ws://").replace("https://", "wss://")
            + "/signalk/v1/stream?subscribe=all"
        )

    async def run_inspect(self, queue: asyncio.Queue) -> None:
        """Single-shot connection for inspect mode (no reconnect)."""
        logger.info("Inspect: connecting to %s", self._inspect_ws_url)
        async with websockets.connect(
            self._inspect_ws_url,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=15,
        ) as ws:
            try:
                hello_raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                hello = json.loads(hello_raw)
                if "self" in hello and hello["self"]:
                    self._self_context = hello["self"]
                logger.info("Inspect: self context = %s", self._self_context)
            except Exception as exc:
                logger.warning("Inspect hello failed: %s", exc)

            self._connected = True
            async for raw_msg in ws:
                await self._handle_message(raw_msg, queue)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _extract_source_label(update_block: Dict[str, Any]) -> Optional[str]:
    """Best-effort extraction of source label from an update block."""
    # $source is a string reference; source is the full source object
    if "$source" in update_block:
        return str(update_block["$source"])
    src = update_block.get("source")
    if isinstance(src, dict):
        return src.get("label") or src.get("type") or str(src)
    return None
