"""Signal K delta publisher for wave estimates.

Formats MotionEstimate data as Signal K delta messages and sends them
back to the server via WebSocket.  Uses the same connection as the
SignalKClient reader (bidirectional WebSocket).

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

No formal device registration is needed on unsecured Signal K servers;
the ``source`` object serves as implicit registration.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import Config, DEFAULT_CONFIG
from models import MotionEstimate
from paths import (
    HEAVE,
    WAVE_COMFORT_PROXY,
    WAVE_ENCOUNTER_DIRECTION,
    WAVE_ENCOUNTER_PERIOD,
    WAVE_MOTION_REGIME,
    WAVE_MOTION_SEVERITY,
    WAVE_PERIOD,
    WAVE_PERIOD_CONFIDENCE,
    WAVE_SIGNIFICANT_HEIGHT,
    WAVE_TRUE_PERIOD,
    WAVE_TRUE_WAVELENGTH,
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

    # Note: WAVE_SIGNIFICANT_HEIGHT and HEAVE are not yet populated —
    # they require accelerometer-based wave height estimation (future).

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


async def publish_delta(
    ws: Any,
    me: MotionEstimate,
    self_context: str = "vessels.self",
    source_label: str = "boat_wave_state",
) -> bool:
    """Send a delta message for the given MotionEstimate via WebSocket.

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
