"""Tests for Signal K delta parsing and self-path filtering."""

from __future__ import annotations

import asyncio
import json
import sys
import os
import pytest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from config import Config
from models import SignalKValueUpdate
from signalk_client import SignalKClient, _parse_sk_timestamp, _extract_source_label
from state_store import SelfStateStore
from paths import ATTITUDE_ROLL, ATTITUDE


# --------------------------------------------------------------------------- #
# Timestamp parsing                                                            #
# --------------------------------------------------------------------------- #


def test_parse_sk_timestamp_utc_z():
    ts = _parse_sk_timestamp("2024-06-01T12:00:00.000Z")
    assert ts is not None
    assert ts.tzinfo is not None
    assert ts.year == 2024
    assert ts.hour == 12


def test_parse_sk_timestamp_offset():
    ts = _parse_sk_timestamp("2024-06-01T14:00:00+02:00")
    assert ts is not None
    assert ts.tzinfo is not None


def test_parse_sk_timestamp_none():
    assert _parse_sk_timestamp(None) is None
    assert _parse_sk_timestamp("") is None
    assert _parse_sk_timestamp("not-a-date") is None


# --------------------------------------------------------------------------- #
# Source label extraction                                                      #
# --------------------------------------------------------------------------- #


def test_extract_source_label_dollar_source():
    block = {"$source": "my.sensor", "values": []}
    assert _extract_source_label(block) == "my.sensor"


def test_extract_source_label_source_dict():
    block = {"source": {"label": "GPS", "type": "NMEA0183"}, "values": []}
    assert _extract_source_label(block) == "GPS"


def test_extract_source_label_missing():
    block = {"values": []}
    assert _extract_source_label(block) is None


# --------------------------------------------------------------------------- #
# Self context filtering                                                       #
# --------------------------------------------------------------------------- #


def test_self_filter_vessels_self():
    config = Config()
    client = SignalKClient(config)
    assert client._is_self("vessels.self") is True


def test_self_filter_urn_after_hello():
    config = Config()
    client = SignalKClient(config)
    # Simulate hello setting a URN context
    client._self_context = "vessels.urn:mrn:imo:mmsi:123456789"
    assert client._is_self("vessels.urn:mrn:imo:mmsi:123456789") is True
    assert client._is_self("vessels.urn:mrn:imo:mmsi:999999999") is False


def test_self_filter_other_vessel():
    config = Config()
    client = SignalKClient(config)
    assert client._is_self("vessels.urn:mrn:imo:mmsi:999") is False


# --------------------------------------------------------------------------- #
# State store: delta merging                                                    #
# --------------------------------------------------------------------------- #


def _make_update(path: str, value, received_at=None) -> SignalKValueUpdate:
    if received_at is None:
        received_at = datetime.now(timezone.utc)
    return SignalKValueUpdate(
        path=path,
        value=value,
        source="test",
        timestamp=received_at,
        received_at=received_at,
    )


def test_state_store_scalar():
    config = Config()
    store = SelfStateStore(config)
    store.apply_update_sync(_make_update(ATTITUDE_ROLL, 0.15))
    snap = store.snapshot()
    assert snap.roll == pytest.approx(0.15)


def test_state_store_compound_attitude():
    config = Config()
    store = SelfStateStore(config)
    # Compound object update
    compound = {"roll": 0.10, "pitch": -0.05, "yaw": 1.23}
    store.apply_update_sync(_make_update(ATTITUDE, compound))
    snap = store.snapshot()
    assert snap.roll == pytest.approx(0.10)
    assert snap.pitch == pytest.approx(-0.05)
    assert snap.yaw == pytest.approx(1.23)


def test_state_store_partial_compound():
    """Partial compound attitude update should only overwrite specified subkeys."""
    config = Config()
    store = SelfStateStore(config)
    store.apply_update_sync(_make_update(ATTITUDE_ROLL, 0.20))
    store.apply_update_sync(_make_update(ATTITUDE, {"pitch": 0.05}))
    snap = store.snapshot()
    # roll from previous scalar update should still be there
    assert snap.roll == pytest.approx(0.20)
    assert snap.pitch == pytest.approx(0.05)


def test_state_store_none_value_ignored():
    config = Config()
    store = SelfStateStore(config)
    store.apply_update_sync(_make_update(ATTITUDE_ROLL, 0.30))
    store.apply_update_sync(_make_update(ATTITUDE_ROLL, None))
    snap = store.snapshot()
    # None update should not overwrite existing value
    assert snap.roll == pytest.approx(0.30)


def test_state_store_freshness():
    import time

    config = Config(stale_threshold_s=1.0)
    store = SelfStateStore(config)
    store.apply_update_sync(_make_update(ATTITUDE_ROLL, 0.10))
    snap = store.snapshot()
    assert snap.field_valid["roll"] is True

    time.sleep(1.1)
    snap2 = store.snapshot()
    assert snap2.field_valid["roll"] is False


def test_state_store_position():
    config = Config()
    store = SelfStateStore(config)
    from paths import POSITION

    pos = {"latitude": 51.5, "longitude": -0.1}
    store.apply_update_sync(_make_update(POSITION, pos))
    snap = store.snapshot()
    assert snap.latitude == pytest.approx(51.5)
    assert snap.longitude == pytest.approx(-0.1)


# --------------------------------------------------------------------------- #
# on_connect callback                                                          #
# --------------------------------------------------------------------------- #


def _local_config(port: int, **overrides: object) -> Config:
    """Build a Config pointing at a local test WebSocket server."""
    return Config(
        base_url=f"http://127.0.0.1:{port}",
        ws_url=f"ws://127.0.0.1:{port}/signalk/v1/stream?subscribe=none",
        **overrides,  # type: ignore[arg-type]
    )


def test_on_connect_registers_callback():
    """on_connect should store the callback in the internal list."""
    config = Config()
    client = SignalKClient(config)

    async def _dummy() -> None:
        pass

    client.on_connect(_dummy)
    assert len(client._on_connect_callbacks) == 1
    assert client._on_connect_callbacks[0] is _dummy


def test_on_connect_multiple_callbacks():
    """Multiple callbacks should all be registered in order."""
    config = Config()
    client = SignalKClient(config)

    calls: list[str] = []

    async def _cb_a() -> None:
        calls.append("a")

    async def _cb_b() -> None:
        calls.append("b")

    client.on_connect(_cb_a)
    client.on_connect(_cb_b)
    assert len(client._on_connect_callbacks) == 2
    assert client._on_connect_callbacks[0] is _cb_a
    assert client._on_connect_callbacks[1] is _cb_b


@pytest.mark.asyncio
async def test_on_connect_callbacks_fire_on_connect():
    """Callbacks should fire when _connect_and_stream runs successfully.

    We simulate a minimal WebSocket server inline to verify the callback
    fires after subscription (connected=True) without depending on a real
    Signal K server.
    """
    import websockets

    call_log: list[str] = []

    async def _handler(ws) -> None:
        # Send a minimal hello
        hello = json.dumps({"name": "test", "version": "0.0.1", "self": "vessels.self"})
        await ws.send(hello)
        # Receive and discard the subscription message
        await ws.recv()
        # Send one delta then close
        delta = json.dumps(
            {
                "context": "vessels.self",
                "updates": [
                    {
                        "values": [{"path": "navigation.attitude.roll", "value": 0.01}],
                        "timestamp": "2024-01-01T00:00:00Z",
                    }
                ],
            }
        )
        await ws.send(delta)
        await ws.close()

    async def _on_connect_cb() -> None:
        call_log.append("connected")

    server = await websockets.serve(_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    config = _local_config(port)
    client = SignalKClient(config)
    client.on_connect(_on_connect_cb)

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    # _connect_and_stream will return once the WS closes
    await client._connect_and_stream(queue)

    server.close()
    await server.wait_closed()

    assert "connected" in call_log
    assert len(call_log) == 1


@pytest.mark.asyncio
async def test_on_connect_callback_error_does_not_break_streaming():
    """A failing callback must not prevent the message streaming loop."""
    import websockets

    good_calls: list[str] = []

    async def _handler(ws) -> None:
        hello = json.dumps({"name": "test", "version": "0.0.1", "self": "vessels.self"})
        await ws.send(hello)
        await ws.recv()  # subscription
        delta = json.dumps(
            {
                "context": "vessels.self",
                "updates": [
                    {
                        "values": [{"path": "navigation.attitude.roll", "value": 0.01}],
                        "timestamp": "2024-01-01T00:00:00Z",
                    }
                ],
            }
        )
        await ws.send(delta)
        await ws.close()

    async def _bad_cb() -> None:
        raise RuntimeError("deliberate test error")

    async def _good_cb() -> None:
        good_calls.append("ok")

    server = await websockets.serve(_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    config = _local_config(port)
    client = SignalKClient(config)
    client.on_connect(_bad_cb)
    client.on_connect(_good_cb)

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    await client._connect_and_stream(queue)

    server.close()
    await server.wait_closed()

    # The good callback should still have run despite the bad one raising
    assert "ok" in good_calls
    # And the delta should have been processed (queue should have items)
    assert not queue.empty()


@pytest.mark.asyncio
async def test_on_connect_fires_on_every_reconnect():
    """Callback should fire on every connect, not just the first one."""
    import websockets

    connect_count = 0
    call_log: list[int] = []

    async def _handler(ws) -> None:
        nonlocal connect_count
        connect_count += 1
        hello = json.dumps({"name": "test", "version": "0.0.1", "self": "vessels.self"})
        await ws.send(hello)
        await ws.recv()  # subscription
        # Close immediately to trigger reconnect
        await ws.close()

    async def _on_connect_cb() -> None:
        call_log.append(connect_count)

    server = await websockets.serve(_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    config = _local_config(port, reconnect_delays=[0.1])
    client = SignalKClient(config)
    client.on_connect(_on_connect_cb)

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    # Run the client for a short duration to allow 2+ connect cycles
    try:
        await asyncio.wait_for(client.run(queue), timeout=1.5)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass

    server.close()
    await server.wait_closed()

    # Should have connected (and called back) at least twice
    assert len(call_log) >= 2
