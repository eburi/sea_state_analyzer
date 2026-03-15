"""Tests for IMU auto-detection: registry and I2C scanning.

All tests mock smbus2 so no real I2C hardware is needed.
"""

from __future__ import annotations

import sys
from typing import Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from imu_registry import (
    IMU_REGISTRY,
    all_scan_addresses,
    get_chip_info,
)
from imu_detect import (
    DetectionResult,
    _probe_address,
    _read_register,
    _scan_bus,
    detect_imu,
    detect_imu_on_bus,
    discover_i2c_buses,
)


# --------------------------------------------------------------------------- #
# Fake SMBus for detection tests                                               #
# --------------------------------------------------------------------------- #


class FakeDetectBus:
    """Minimal SMBus mock that simulates devices at given addresses.

    Devices are defined as {address: {register: value}} dicts.
    """

    def __init__(self, devices: Dict[int, Dict[int, int]]) -> None:
        self._devices = devices
        self.closed = False

    def write_quick(self, address: int) -> None:
        if address not in self._devices:
            raise OSError(f"No device at 0x{address:02X}")

    def read_byte_data(self, address: int, register: int) -> int:
        if address not in self._devices:
            raise OSError(f"No device at 0x{address:02X}")
        regs = self._devices[address]
        return regs.get(register, 0x00)

    def close(self) -> None:
        self.closed = True


# --------------------------------------------------------------------------- #
# Registry tests                                                               #
# --------------------------------------------------------------------------- #


class TestIMURegistry:
    def test_registry_not_empty(self) -> None:
        assert len(IMU_REGISTRY) > 0

    def test_all_entries_have_required_fields(self) -> None:
        for chip in IMU_REGISTRY:
            assert chip.chip_name
            assert len(chip.i2c_addresses) > 0
            assert 0x00 <= chip.who_am_i_register <= 0xFF
            assert 0x00 <= chip.expected_id <= 0xFF

    def test_icm20948_in_registry(self) -> None:
        chip = get_chip_info("ICM-20948")
        assert chip is not None
        assert chip.expected_id == 0xEA
        assert chip.who_am_i_register == 0x00
        assert 0x68 in chip.i2c_addresses
        assert chip.has_magnetometer is True

    def test_mpu6050_in_registry(self) -> None:
        chip = get_chip_info("MPU-6050")
        assert chip is not None
        assert chip.expected_id == 0x68
        assert chip.who_am_i_register == 0x75

    def test_bno055_in_registry(self) -> None:
        chip = get_chip_info("BNO055")
        assert chip is not None
        assert chip.expected_id == 0xA0
        assert 0x28 in chip.i2c_addresses

    def test_get_chip_info_unknown(self) -> None:
        assert get_chip_info("NONEXISTENT-1234") is None

    def test_all_scan_addresses_sorted_unique(self) -> None:
        addrs = all_scan_addresses()
        assert addrs == sorted(set(addrs))
        # Should include at least 0x68 and 0x28
        assert 0x68 in addrs
        assert 0x28 in addrs

    def test_no_duplicate_chip_ids_at_same_register(self) -> None:
        """Two chips at the same address + same WHO_AM_I register
        must have different expected IDs (otherwise detection is ambiguous)."""
        seen: Dict[tuple, str] = {}
        for chip in IMU_REGISTRY:
            for addr in chip.i2c_addresses:
                key = (addr, chip.who_am_i_register, chip.expected_id)
                if key in seen:
                    pytest.fail(
                        f"{chip.chip_name} and {seen[key]} share the same "
                        f"(addr=0x{addr:02X}, reg=0x{chip.who_am_i_register:02X}, "
                        f"id=0x{chip.expected_id:02X}) — detection would be ambiguous"
                    )
                seen[key] = chip.chip_name


# --------------------------------------------------------------------------- #
# Low-level probe/read tests                                                   #
# --------------------------------------------------------------------------- #


class TestProbeAndRead:
    def test_probe_address_found(self) -> None:
        bus = FakeDetectBus({0x68: {}})
        assert _probe_address(bus, 0x68) is True

    def test_probe_address_not_found(self) -> None:
        bus = FakeDetectBus({})
        assert _probe_address(bus, 0x68) is False

    def test_read_register_success(self) -> None:
        bus = FakeDetectBus({0x68: {0x00: 0xEA}})
        assert _read_register(bus, 0x68, 0x00) == 0xEA

    def test_read_register_no_device(self) -> None:
        bus = FakeDetectBus({})
        assert _read_register(bus, 0x68, 0x00) is None

    def test_read_register_default_zero(self) -> None:
        """Unknown register returns 0 (not None) — device exists."""
        bus = FakeDetectBus({0x68: {}})
        assert _read_register(bus, 0x68, 0xFF) == 0x00


# --------------------------------------------------------------------------- #
# Bus scanning tests                                                           #
# --------------------------------------------------------------------------- #


class TestScanBus:
    def test_detect_icm20948(self) -> None:
        """Should detect ICM-20948 at 0x68."""
        bus = FakeDetectBus(
            {
                0x68: {0x00: 0xEA},  # WHO_AM_I for ICM-20948
            }
        )
        result = _scan_bus(bus, bus_number=1)
        assert result is not None
        assert result.chip.chip_name == "ICM-20948"
        assert result.address == 0x68
        assert result.bus_number == 1

    def test_detect_icm20948_alt_address(self) -> None:
        """Should detect ICM-20948 at 0x69."""
        bus = FakeDetectBus(
            {
                0x69: {0x00: 0xEA},
            }
        )
        result = _scan_bus(bus, bus_number=1)
        assert result is not None
        assert result.chip.chip_name == "ICM-20948"
        assert result.address == 0x69

    def test_detect_mpu6050(self) -> None:
        """Should detect MPU-6050 (WHO_AM_I at 0x75, value 0x68)."""
        bus = FakeDetectBus(
            {
                0x68: {
                    0x00: 0x00,  # Not ICM-20948
                    0x75: 0x68,  # MPU-6050
                },
            }
        )
        result = _scan_bus(bus, bus_number=1)
        assert result is not None
        assert result.chip.chip_name == "MPU-6050"
        assert result.address == 0x68

    def test_detect_mpu9250(self) -> None:
        """Should detect MPU-9250 (WHO_AM_I at 0x75, value 0x71)."""
        bus = FakeDetectBus(
            {
                0x68: {
                    0x00: 0x00,
                    0x75: 0x71,
                },
            }
        )
        result = _scan_bus(bus, bus_number=1)
        assert result is not None
        assert result.chip.chip_name == "MPU-9250"

    def test_detect_bno055(self) -> None:
        """Should detect BNO055 at 0x28."""
        bus = FakeDetectBus(
            {
                0x28: {0x00: 0xA0},
            }
        )
        result = _scan_bus(bus, bus_number=1)
        assert result is not None
        assert result.chip.chip_name == "BNO055"
        assert result.address == 0x28

    def test_detect_lsm6dsox(self) -> None:
        """Should detect LSM6DSOX at 0x6A."""
        bus = FakeDetectBus(
            {
                0x6A: {0x0F: 0x6C},
            }
        )
        result = _scan_bus(bus, bus_number=1)
        assert result is not None
        assert result.chip.chip_name == "LSM6DSOX"
        assert result.address == 0x6A

    def test_detect_bmi160(self) -> None:
        """Should detect BMI160 at 0x68."""
        bus = FakeDetectBus(
            {
                0x68: {
                    0x00: 0xD1,  # BMI160
                    0x75: 0x00,  # Not MPU
                },
            }
        )
        result = _scan_bus(bus, bus_number=1)
        assert result is not None
        assert result.chip.chip_name == "BMI160"

    def test_no_device_returns_none(self) -> None:
        """Empty bus should return None."""
        bus = FakeDetectBus({})
        result = _scan_bus(bus, bus_number=1)
        assert result is None

    def test_unknown_device_returns_none(self) -> None:
        """Device with unrecognised WHO_AM_I should return None."""
        bus = FakeDetectBus(
            {
                0x68: {0x00: 0xFF, 0x75: 0xFF},
            }
        )
        result = _scan_bus(bus, bus_number=1)
        assert result is None

    def test_multiple_devices_returns_first(self) -> None:
        """When multiple IMUs are present, returns the first found
        (lowest address in scan order)."""
        bus = FakeDetectBus(
            {
                0x28: {0x00: 0xA0},  # BNO055
                0x68: {0x00: 0xEA},  # ICM-20948
            }
        )
        result = _scan_bus(bus, bus_number=1)
        assert result is not None
        # 0x28 is scanned before 0x68
        assert result.chip.chip_name == "BNO055"

    def test_icm20649_distinguished_from_icm20948(self) -> None:
        """ICM-20649 (0xE1) vs ICM-20948 (0xEA) at same register."""
        bus = FakeDetectBus(
            {
                0x68: {0x00: 0xE1},
            }
        )
        result = _scan_bus(bus, bus_number=1)
        assert result is not None
        assert result.chip.chip_name == "ICM-20649"


# --------------------------------------------------------------------------- #
# High-level detect_imu tests                                                  #
# --------------------------------------------------------------------------- #


class TestDetectIMU:
    def test_detect_imu_no_smbus(self) -> None:
        """detect_imu_on_bus returns None when smbus2 is not installed."""
        saved = sys.modules.get("smbus2")
        sys.modules["smbus2"] = None  # type: ignore[assignment]
        try:
            result = detect_imu_on_bus(bus_number=99)
            assert result is None
        finally:
            if saved is not None:
                sys.modules["smbus2"] = saved
            else:
                sys.modules.pop("smbus2", None)

    def test_detect_imu_bad_bus(self) -> None:
        """detect_imu_on_bus returns None for a non-existent bus."""
        fake_smbus2 = MagicMock()
        fake_smbus2.SMBus.side_effect = OSError("No such bus")
        with patch.dict(sys.modules, {"smbus2": fake_smbus2}):
            result = detect_imu_on_bus(bus_number=99)
            assert result is None

    def test_detect_imu_multi_bus(self) -> None:
        """detect_imu scans multiple buses and returns first hit."""
        call_count = 0

        def mock_detect(bus_number: int) -> Optional[DetectionResult]:
            nonlocal call_count
            call_count += 1
            if bus_number == 3:
                return DetectionResult(
                    chip=get_chip_info("ICM-20948"),  # type: ignore[arg-type]
                    address=0x68,
                    bus_number=3,
                )
            return None

        with patch("imu_detect.detect_imu_on_bus", side_effect=mock_detect):
            result = detect_imu(bus_numbers=[1, 2, 3, 4])
            assert result is not None
            assert result.bus_number == 3
            # Should have stopped after finding on bus 3, not scanning bus 4
            assert call_count == 3

    def test_detect_imu_auto_discovers_buses(self) -> None:
        """detect_imu() with no args auto-discovers buses from /dev."""
        with patch("imu_detect.discover_i2c_buses", return_value=[0, 1, 5]):
            with patch("imu_detect.detect_imu_on_bus", return_value=None) as mock_bus:
                result = detect_imu()
                assert result is None
                # Should have scanned buses 0, 1, 5
                assert mock_bus.call_count == 3
                mock_bus.assert_any_call(0)
                mock_bus.assert_any_call(1)
                mock_bus.assert_any_call(5)

    def test_detect_imu_fallback_bus1_when_no_buses_found(self) -> None:
        """detect_imu() falls back to [1] when discover finds nothing."""
        with patch("imu_detect.discover_i2c_buses", return_value=[]):
            with patch("imu_detect.detect_imu_on_bus", return_value=None) as mock_bus:
                result = detect_imu()
                assert result is None
                mock_bus.assert_called_once_with(1)


# --------------------------------------------------------------------------- #
# discover_i2c_buses tests                                                     #
# --------------------------------------------------------------------------- #


class TestDiscoverI2CBuses:
    def test_discovers_standard_buses(self) -> None:
        """Should parse /dev/i2c-N entries correctly."""
        fake_paths = ["/dev/i2c-0", "/dev/i2c-1", "/dev/i2c-3"]
        with patch("imu_detect.glob.glob", return_value=fake_paths):
            buses = discover_i2c_buses()
            assert buses == [0, 1, 3]

    def test_returns_empty_when_no_buses(self) -> None:
        """Should return empty list when no i2c devices exist."""
        with patch("imu_detect.glob.glob", return_value=[]):
            buses = discover_i2c_buses()
            assert buses == []

    def test_ignores_non_numeric_entries(self) -> None:
        """Should skip entries that don't match i2c-N pattern."""
        fake_paths = ["/dev/i2c-1", "/dev/i2c-foo", "/dev/i2c-3"]
        with patch("imu_detect.glob.glob", return_value=fake_paths):
            buses = discover_i2c_buses()
            assert buses == [1, 3]

    def test_returns_sorted(self) -> None:
        """Should return bus numbers in sorted order."""
        fake_paths = ["/dev/i2c-10", "/dev/i2c-1", "/dev/i2c-5"]
        with patch("imu_detect.glob.glob", return_value=fake_paths):
            buses = discover_i2c_buses()
            assert buses == [1, 5, 10]

    def test_handles_high_bus_numbers(self) -> None:
        """Should handle bus numbers up to 20 and beyond."""
        fake_paths = [f"/dev/i2c-{i}" for i in range(21)]
        with patch("imu_detect.glob.glob", return_value=fake_paths):
            buses = discover_i2c_buses()
            assert buses == list(range(21))
            assert len(buses) == 21


# --------------------------------------------------------------------------- #
# DetectionResult tests                                                        #
# --------------------------------------------------------------------------- #


class TestDetectionResult:
    def test_str_representation(self) -> None:
        chip = get_chip_info("ICM-20948")
        assert chip is not None
        result = DetectionResult(chip=chip, address=0x69, bus_number=1)
        s = str(result)
        assert "ICM-20948" in s
        assert "0x69" in s.lower()

    def test_chip_info_preserved(self) -> None:
        chip = get_chip_info("BNO055")
        assert chip is not None
        result = DetectionResult(chip=chip, address=0x28, bus_number=1)
        assert result.chip.has_magnetometer is True
        assert result.chip.chip_name == "BNO055"


# --------------------------------------------------------------------------- #
# Config integration tests                                                     #
# --------------------------------------------------------------------------- #


class TestConfigAutoDetect:
    def test_default_auto_detect_enabled(self) -> None:
        from config import Config

        c = Config()
        assert c.imu_auto_detect is True

    def test_auto_detect_disableable(self) -> None:
        from config import Config

        c = Config(imu_auto_detect=False)
        assert c.imu_auto_detect is False
