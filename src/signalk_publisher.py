"""Signal K delta publisher for wave estimates.

Formats MotionEstimate data as Signal K delta messages and publishes
them to the Signal K server via authenticated WebSocket.

The app obtains a JWT token through the Signal K device access request
flow (see ``signalk_auth.py``).  The token is included as an
``Authorization: Bearer`` header on the WebSocket connection, enabling
write access to the Signal K data model.

Delta format::

    {
      "context": "vessels.self",
      "updates": [{
        "source": {"label": "boat_wave_state", "type": "signalk"},
        "timestamp": "2024-06-01T12:00:00Z",
        "values": [
          {"path": "environment.water.waves.motionSeverity", "value": 0.42},
          ...
        ]
      }]
    }
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from models import MotionEstimate
from paths import (
    HEAVE,
    WAVE_COMFORT_PROXY,
    WAVE_ENCOUNTER_DIRECTION,
    WAVE_ENCOUNTER_PERIOD,
    WAVE_MOTION_REGIME,
    WAVE_MOTION_SEVERITY,
    WAVE_PATH_META,
    WAVE_PERIOD,
    WAVE_PERIOD_CONFIDENCE,
    WAVE_SIGNIFICANT_HEIGHT,
    WAVE_SWELL_1_CONFIDENCE,
    WAVE_SWELL_1_HEIGHT,
    WAVE_SWELL_1_PERIOD,
    WAVE_SWELL_2_CONFIDENCE,
    WAVE_SWELL_2_HEIGHT,
    WAVE_SWELL_2_PERIOD,
    WAVE_TRUE_PERIOD,
    WAVE_TRUE_WAVELENGTH,
    WAVE_WIND_WAVE_CONFIDENCE,
    WAVE_WIND_WAVE_HEIGHT,
    WAVE_WIND_WAVE_PERIOD,
)

logger = logging.getLogger(__name__)


def _motion_estimate_to_values(
    me: MotionEstimate,
) -> List[Dict[str, Any]]:
    """Convert a MotionEstimate into a list of Signal K path/value pairs.

    Only non-None numeric/string fields are included.  String values
    (regime, direction) are sent as-is.  Numeric values are rounded
    to a reasonable precision to keep delta messages compact.
    """
    pairs: List[Tuple[str, Any]] = []

    # Severity (0-1 float)
    sev = me.motion_severity_smoothed or me.motion_severity
    if sev is not None:
        pairs.append((WAVE_MOTION_SEVERITY, round(sev, 3)))

    # Regime (string: calm / moderate / active / heavy)
    if me.motion_regime is not None:
        pairs.append((WAVE_MOTION_REGIME, me.motion_regime))

    # Encounter period (seconds)
    if me.encounter_period_estimate is not None:
        pairs.append((WAVE_ENCOUNTER_PERIOD, round(me.encounter_period_estimate, 2)))
        # Also publish as the primary "period" path
        pairs.append((WAVE_PERIOD, round(me.encounter_period_estimate, 2)))

    # Doppler-corrected true wave period
    if me.true_wave_period is not None and me.doppler_correction_valid:
        pairs.append((WAVE_TRUE_PERIOD, round(me.true_wave_period, 2)))

    # True wavelength
    if me.true_wavelength is not None and me.doppler_correction_valid:
        pairs.append((WAVE_TRUE_WAVELENGTH, round(me.true_wavelength, 1)))

    # Encounter direction (string)
    if me.encounter_direction is not None:
        pairs.append((WAVE_ENCOUNTER_DIRECTION, me.encounter_direction))

    # Period confidence (0-1)
    if me.period_confidence is not None:
        pairs.append((WAVE_PERIOD_CONFIDENCE, round(me.period_confidence, 2)))

    # Comfort proxy (0-1)
    if me.comfort_proxy is not None:
        pairs.append((WAVE_COMFORT_PROXY, round(me.comfort_proxy, 3)))

    # Significant wave height (metres) — from IMU accelerometer
    if me.significant_height is not None:
        pairs.append((WAVE_SIGNIFICANT_HEIGHT, round(me.significant_height, 2)))

    # Heave displacement (metres) — from Kalman filter
    if me.heave is not None:
        pairs.append((HEAVE, round(me.heave, 3)))

    # Spectral partitions — wind-wave
    if me.wind_wave_height is not None:
        pairs.append((WAVE_WIND_WAVE_HEIGHT, round(me.wind_wave_height, 2)))
    if me.wind_wave_period is not None:
        pairs.append((WAVE_WIND_WAVE_PERIOD, round(me.wind_wave_period, 1)))
    if me.wind_wave_confidence is not None:
        pairs.append((WAVE_WIND_WAVE_CONFIDENCE, round(me.wind_wave_confidence, 2)))

    # Spectral partitions — primary swell
    if me.swell_1_height is not None:
        pairs.append((WAVE_SWELL_1_HEIGHT, round(me.swell_1_height, 2)))
    if me.swell_1_period is not None:
        pairs.append((WAVE_SWELL_1_PERIOD, round(me.swell_1_period, 1)))
    if me.swell_1_confidence is not None:
        pairs.append((WAVE_SWELL_1_CONFIDENCE, round(me.swell_1_confidence, 2)))

    # Spectral partitions — secondary swell
    if me.swell_2_height is not None:
        pairs.append((WAVE_SWELL_2_HEIGHT, round(me.swell_2_height, 2)))
    if me.swell_2_period is not None:
        pairs.append((WAVE_SWELL_2_PERIOD, round(me.swell_2_period, 1)))
    if me.swell_2_confidence is not None:
        pairs.append((WAVE_SWELL_2_CONFIDENCE, round(me.swell_2_confidence, 2)))

    return [{"path": path, "value": value} for path, value in pairs]


def build_delta_message(
    me: MotionEstimate,
    self_context: str = "vessels.self",
    source_label: str = "boat_wave_state",
) -> Optional[str]:
    """Build a JSON delta message string from a MotionEstimate.

    Returns None if the estimate has no publishable values (e.g. all
    fields are None).
    """
    values = _motion_estimate_to_values(me)
    if not values:
        return None

    delta = {
        "context": self_context,
        "updates": [
            {
                "source": {
                    "label": source_label,
                    "type": "signalk",
                },
                "timestamp": me.timestamp.isoformat().replace("+00:00", "Z"),
                "values": values,
            }
        ],
    }
    return json.dumps(delta, separators=(",", ":"))


def build_meta_delta(
    self_context: str = "vessels.self",
) -> str:
    """Build a JSON meta delta message for all wave publish paths.

    Signal K meta deltas use ``"meta"`` instead of ``"values"`` in the
    update block.  Each entry maps a path to its metadata (units,
    description, displayName, etc.).

    This should be sent once on startup (after authentication) so that
    Signal K dashboards and gauges can display proper units and labels.

    Returns:
        A JSON string ready to send over the WebSocket.
    """
    meta_entries: List[Dict[str, Any]] = [
        {"path": path, "value": dict(meta)}
        for path, meta in WAVE_PATH_META.items()
    ]
    delta = {
        "context": self_context,
        "updates": [
            {
                "meta": meta_entries,
            }
        ],
    }
    return json.dumps(delta, separators=(",", ":"))


async def publish_delta(
    ws: Any,
    me: MotionEstimate,
    self_context: str = "vessels.self",
    source_label: str = "boat_wave_state",
) -> bool:
    """Send a delta message for the given MotionEstimate via WebSocket.

    Requires an authenticated WebSocket connection (see ``signalk_auth.py``).

    Args:
        ws: An open websockets connection (websockets.WebSocketClientProtocol).
        me: The motion estimate to publish.
        self_context: Signal K self context string.
        source_label: Source label for the delta.

    Returns:
        True if the message was sent successfully, False otherwise.
    """
    msg = build_delta_message(me, self_context, source_label)
    if msg is None:
        logger.debug("No publishable values in MotionEstimate, skipping")
        return False

    try:
        await ws.send(msg)
        logger.debug("Published delta (%d bytes, %d values)",
                      len(msg), msg.count('"path"'))
        return True
    except Exception as exc:
        logger.warning("Failed to publish delta: %s", exc)
        return False
