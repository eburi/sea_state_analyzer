"""IMU chip registry for auto-detection.

Each entry describes how to identify a specific IMU chip on an I2C bus:
its possible addresses, which register to read (WHO_AM_I), and the
expected value.

Sources:
- Adafruit CircuitPython drivers (ICM20X, MPU6050, BNO055, LSM6DS)
- InvenSense / Bosch / STMicro datasheets
- This project's own ICM-20948 driver (imu_reader.py)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class IMUChipInfo:
    """Identification parameters for a single IMU chip."""

    chip_name: str
    i2c_addresses: Tuple[int, ...]
    who_am_i_register: int
    expected_id: int
    has_magnetometer: bool
    notes: str = ""


# --------------------------------------------------------------------------- #
# Verified chip registry                                                       #
# --------------------------------------------------------------------------- #
# Order matters: chips sharing I2C addresses (0x68/0x69) are disambiguated
# by reading different WHO_AM_I registers and comparing expected values.

IMU_REGISTRY: List[IMUChipInfo] = [
    # --- InvenSense ICM-209xx family (WHO_AM_I at 0x00) ---
    IMUChipInfo(
        chip_name="ICM-20948",
        i2c_addresses=(0x68, 0x69),
        who_am_i_register=0x00,
        expected_id=0xEA,
        has_magnetometer=True,
        notes="9-DOF with AK09916 magnetometer; bank-switched registers",
    ),
    IMUChipInfo(
        chip_name="ICM-20649",
        i2c_addresses=(0x68, 0x69),
        who_am_i_register=0x00,
        expected_id=0xE1,
        has_magnetometer=False,
        notes="6-DOF high-range accel/gyro; bank-switched registers",
    ),
    # --- InvenSense MPU family (WHO_AM_I at 0x75) ---
    IMUChipInfo(
        chip_name="MPU-9250",
        i2c_addresses=(0x68, 0x69),
        who_am_i_register=0x75,
        expected_id=0x71,
        has_magnetometer=True,
        notes="9-DOF with AK8963 magnetometer",
    ),
    IMUChipInfo(
        chip_name="MPU-6050",
        i2c_addresses=(0x68, 0x69),
        who_am_i_register=0x75,
        expected_id=0x68,
        has_magnetometer=False,
        notes="6-DOF accel/gyro; very common breakout board",
    ),
    # --- Bosch (WHO_AM_I at 0x00) ---
    IMUChipInfo(
        chip_name="BMI160",
        i2c_addresses=(0x68, 0x69),
        who_am_i_register=0x00,
        expected_id=0xD1,
        has_magnetometer=False,
        notes="6-DOF accel/gyro",
    ),
    # --- Bosch BNO055 (different address range, WHO_AM_I at 0x00) ---
    IMUChipInfo(
        chip_name="BNO055",
        i2c_addresses=(0x28, 0x29),
        who_am_i_register=0x00,
        expected_id=0xA0,
        has_magnetometer=True,
        notes="9-DOF with onboard sensor fusion; Euler/quaternion output",
    ),
    # --- STMicro LSM6DS family (WHO_AM_I at 0x0F) ---
    IMUChipInfo(
        chip_name="LSM6DSOX",
        i2c_addresses=(0x6A, 0x6B),
        who_am_i_register=0x0F,
        expected_id=0x6C,
        has_magnetometer=False,
        notes="6-DOF accel/gyro; machine-learning core",
    ),
    IMUChipInfo(
        chip_name="LSM6DS3",
        i2c_addresses=(0x6A, 0x6B),
        who_am_i_register=0x0F,
        expected_id=0x69,
        has_magnetometer=False,
        notes="6-DOF accel/gyro",
    ),
]

# Lookup helpers
_BY_NAME: Dict[str, IMUChipInfo] = {c.chip_name: c for c in IMU_REGISTRY}


def get_chip_info(name: str) -> IMUChipInfo | None:
    """Return chip info by name, or None if not in registry."""
    return _BY_NAME.get(name)


def all_scan_addresses() -> List[int]:
    """Return sorted, deduplicated list of all I2C addresses to probe."""
    addrs: set[int] = set()
    for chip in IMU_REGISTRY:
        addrs.update(chip.i2c_addresses)
    return sorted(addrs)
