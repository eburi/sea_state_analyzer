"""IMU auto-detection over I2C.

Scans I2C buses for known IMU chips by probing WHO_AM_I registers
against the chip registry.  All I2C access is synchronous (smbus2)
and expected to be called from an executor thread.

Usage::

    from imu_detect import detect_imu

    result = detect_imu(bus_number=1)
    if result is not None:
        chip_info, address = result
        print(f"Found {chip_info.chip_name} at 0x{address:02X}")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from imu_registry import IMUChipInfo, IMU_REGISTRY, all_scan_addresses

logger = logging.getLogger(__name__)


@dataclass
class DetectionResult:
    """Result of a successful IMU detection."""
    chip: IMUChipInfo
    address: int
    bus_number: int

    def __str__(self) -> str:
        return (
            f"{self.chip.chip_name} at bus={self.bus_number} "
            f"addr=0x{self.address:02X}"
        )


def _probe_address(bus: "smbus2.SMBus", address: int) -> bool:  # type: ignore[name-defined]
    """Check if any device ACKs on the given address.

    Uses a zero-length quick-write; returns False on NACK / OS error.
    """
    try:
        # write_quick sends a single address byte and checks ACK.
        # This is the standard i2cdetect approach.
        bus.write_quick(address)
        return True
    except OSError:
        return False


def _read_register(bus: "smbus2.SMBus", address: int, register: int) -> Optional[int]:  # type: ignore[name-defined]
    """Read a single byte from (address, register). Returns None on error."""
    try:
        return bus.read_byte_data(address, register)
    except OSError:
        return None


def detect_imu_on_bus(bus_number: int = 1) -> Optional[DetectionResult]:
    """Scan a single I2C bus for the first recognised IMU chip.

    Returns a DetectionResult on success, or None if no known chip found.

    This function is **synchronous and blocking** — run it in an executor
    from async code.
    """
    try:
        from smbus2 import SMBus
    except ImportError:
        logger.debug("smbus2 not available — cannot scan I2C bus")
        return None

    try:
        bus = SMBus(bus_number)
    except OSError as exc:
        logger.debug("Cannot open I2C bus %d: %s", bus_number, exc)
        return None

    try:
        return _scan_bus(bus, bus_number)
    finally:
        bus.close()


def _scan_bus(bus: "smbus2.SMBus", bus_number: int) -> Optional[DetectionResult]:  # type: ignore[name-defined]
    """Internal: scan all registry addresses on an open bus."""
    # Collect all unique addresses to probe
    addresses_to_scan = all_scan_addresses()

    # For each address that ACKs, try all matching chip definitions
    for addr in addresses_to_scan:
        if not _probe_address(bus, addr):
            continue
        logger.debug("I2C device ACK at bus=%d addr=0x%02X", bus_number, addr)

        # Find all chips that could live at this address
        candidates = [
            chip for chip in IMU_REGISTRY
            if addr in chip.i2c_addresses
        ]

        for chip in candidates:
            value = _read_register(bus, addr, chip.who_am_i_register)
            if value is None:
                continue
            if value == chip.expected_id:
                logger.info(
                    "Detected %s at bus=%d addr=0x%02X "
                    "(WHO_AM_I[0x%02X]=0x%02X)",
                    chip.chip_name, bus_number, addr,
                    chip.who_am_i_register, value,
                )
                return DetectionResult(chip=chip, address=addr, bus_number=bus_number)
            else:
                logger.debug(
                    "Chip %s not matched at 0x%02X: "
                    "WHO_AM_I[0x%02X]=0x%02X (expected 0x%02X)",
                    chip.chip_name, addr,
                    chip.who_am_i_register, value, chip.expected_id,
                )

    logger.info("No recognised IMU found on I2C bus %d", bus_number)
    return None


def detect_imu(bus_numbers: Optional[List[int]] = None) -> Optional[DetectionResult]:
    """Scan one or more I2C buses for a known IMU chip.

    Args:
        bus_numbers: List of I2C bus numbers to scan. Defaults to [1]
                     (the standard bus on Raspberry Pi).

    Returns:
        DetectionResult for the first chip found, or None.
    """
    if bus_numbers is None:
        bus_numbers = [1]

    for bus_num in bus_numbers:
        result = detect_imu_on_bus(bus_num)
        if result is not None:
            return result

    return None
