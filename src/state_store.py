"""Vessel self-state store.

Maintains the latest-known value for every Signal K self path.  Incoming
SignalKValueUpdate objects are merged here.  A consistent InstantSample
snapshot can be read at any time.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from models import FieldState, InstantSample, SignalKValueUpdate
from paths import (
    ATTITUDE,
    ATTITUDE_PITCH,
    ATTITUDE_ROLL,
    ATTITUDE_YAW,
    ATTITUDE_SUBKEYS,
    COURSE_OVER_GROUND_TRUE,
    HEADING_TRUE,
    POSITION,
    RATE_OF_TURN,
    SPEED_OVER_GROUND,
    WIND_ANGLE_APPARENT,
    WIND_ANGLE_TRUE_WATER,
    WIND_SPEED_APPARENT,
    WIND_SPEED_TRUE,
)
from config import Config

logger = logging.getLogger(__name__)


class SelfStateStore:
    """
    Thread-safe (asyncio-safe) store for the latest values of vessel self
    Signal K paths.

    Design constraints:
    - Does NOT keep full history in memory – only the latest value per path.
    - Merges partial delta messages without assuming completeness.
    - Tracks source label and timestamp per field for provenance.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._state: Dict[str, FieldState] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Mutation                                                             #
    # ------------------------------------------------------------------ #

    async def apply_update(self, update: SignalKValueUpdate) -> None:
        """Merge a single SignalKValueUpdate into the state."""
        async with self._lock:
            self._apply(update)

    def apply_update_sync(self, update: SignalKValueUpdate) -> None:
        """Non-async version for use in replay/test code."""
        self._apply(update)

    def _apply(self, update: SignalKValueUpdate) -> None:
        path = update.path
        value = update.value

        if value is None:
            return

        # Handle the compound navigation.attitude object
        if path == ATTITUDE and isinstance(value, dict):
            for subkey in ATTITUDE_SUBKEYS:
                if subkey in value and value[subkey] is not None:
                    sub_path = f"navigation.attitude.{subkey}"
                    try:
                        self._state[sub_path] = FieldState(
                            value=float(value[subkey]),
                            source=update.source,
                            source_timestamp=update.timestamp,
                            received_at=update.received_at,
                        )
                    except (TypeError, ValueError):
                        logger.debug("Could not cast attitude.%s to float", subkey)
            return

        # Scalar value: store as-is (numeric cast where possible)
        try:
            if isinstance(value, (int, float)):
                stored_value: Any = float(value)
            else:
                stored_value = value
        except Exception:
            stored_value = value

        self._state[path] = FieldState(
            value=stored_value,
            source=update.source,
            source_timestamp=update.timestamp,
            received_at=update.received_at,
        )

    # ------------------------------------------------------------------ #
    # Query helpers                                                        #
    # ------------------------------------------------------------------ #

    def _get(self, path: str) -> Optional[FieldState]:
        return self._state.get(path)

    def _val(self, path: str) -> Optional[Any]:
        s = self._state.get(path)
        return s.value if s is not None else None

    def _age(self, path: str, now: datetime) -> Optional[float]:
        s = self._state.get(path)
        return s.age_s(now) if s is not None else None

    def _valid(self, path: str, now: datetime) -> bool:
        a = self._age(path, now)
        if a is None:
            return False
        return a < self._config.stale_threshold_s

    # ------------------------------------------------------------------ #
    # Snapshot                                                             #
    # ------------------------------------------------------------------ #

    def snapshot(self) -> InstantSample:
        """
        Return an InstantSample with the latest known values and freshness
        metadata.  This is the canonical output of the state store and is
        called at the configured sample rate.
        """
        now = datetime.now(timezone.utc)

        field_ages: Dict[str, float] = {}
        field_valid: Dict[str, bool] = {}

        def _record(path: str, field_name: str) -> None:
            a = self._age(path, now)
            field_ages[field_name] = a if a is not None else float("inf")
            field_valid[field_name] = self._valid(path, now)

        _record(ATTITUDE_ROLL, "roll")
        _record(ATTITUDE_PITCH, "pitch")
        _record(ATTITUDE_YAW, "yaw")
        _record(RATE_OF_TURN, "rate_of_turn")
        _record(SPEED_OVER_GROUND, "sog")
        _record(COURSE_OVER_GROUND_TRUE, "cog")
        _record(HEADING_TRUE, "heading")
        _record(WIND_SPEED_TRUE, "wind_speed_true")
        _record(WIND_ANGLE_TRUE_WATER, "wind_angle_true")
        _record(WIND_SPEED_APPARENT, "wind_speed_apparent")
        _record(WIND_ANGLE_APPARENT, "wind_angle_apparent")
        _record(POSITION, "position")

        # Unpack position dict
        pos = self._val(POSITION)
        lat: Optional[float] = None
        lon: Optional[float] = None
        if isinstance(pos, dict):
            try:
                lat = float(pos["latitude"])
                lon = float(pos["longitude"])
            except (KeyError, TypeError, ValueError):
                pass

        return InstantSample(
            timestamp=now,
            roll=self._val(ATTITUDE_ROLL),
            pitch=self._val(ATTITUDE_PITCH),
            yaw=self._val(ATTITUDE_YAW),
            rate_of_turn=self._val(RATE_OF_TURN),
            sog=self._val(SPEED_OVER_GROUND),
            cog=self._val(COURSE_OVER_GROUND_TRUE),
            heading=self._val(HEADING_TRUE),
            wind_speed_true=self._val(WIND_SPEED_TRUE),
            wind_angle_true=self._val(WIND_ANGLE_TRUE_WATER),
            wind_speed_apparent=self._val(WIND_SPEED_APPARENT),
            wind_angle_apparent=self._val(WIND_ANGLE_APPARENT),
            latitude=lat,
            longitude=lon,
            field_ages=field_ages,
            field_valid=field_valid,
        )

    # ------------------------------------------------------------------ #
    # Introspection (for inspect mode)                                     #
    # ------------------------------------------------------------------ #

    def all_paths(self) -> Dict[str, FieldState]:
        """Return a copy of the full internal state map (all paths seen)."""
        return dict(self._state)

    def path_count(self) -> int:
        return len(self._state)
