"""Helpers for merging local sensor channels into canonical samples."""

from __future__ import annotations

from typing import TYPE_CHECKING

from config import Config
from engine import should_use_signalk_attitude
from models import InstantSample

if TYPE_CHECKING:
    from imu_reader import IMUSample


def merge_local_imu_sample(
    sample: InstantSample,
    imu: IMUSample | None,
    config: Config,
) -> InstantSample:
    """Overlay local IMU data onto a Signal K sample when available.

    The canonical attitude source remains Signal K ``navigation.attitude``.
    When no local IMU is present, the sample is returned unchanged so the
    pipeline continues with Signal K roll/pitch/yaw.
    """
    if should_use_signalk_attitude(imu is not None, config):
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

    # Track IMU freshness separately from Signal K path freshness.
    imu_age = (sample.timestamp - imu.timestamp).total_seconds()
    sample.field_ages["imu"] = imu_age
    sample.field_valid["imu"] = imu_age < config.stale_threshold_s
    return sample
