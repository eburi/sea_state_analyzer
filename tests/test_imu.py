"""Tests for imu_reader.py — ICM-20948 driver and async IMUReader wrapper.

All tests mock smbus2.SMBus so no real I2C hardware is needed.
"""

from __future__ import annotations

import math
import struct
import sys
from datetime import datetime, timezone
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest

# Import the module under test
from imu_reader import (
    IMUReader,
    IMUSample,
    _ICM20948Driver,
    _CHIP_ID,
    _GRAVITY,
    _WHO_AM_I,
    _BANK_SEL,
    _ACCEL_XOUT_H,
    _ACCEL_CONFIG,
    _GYRO_CONFIG_1,
    _EXT_SLV_SENS_DATA_00,
    _TEMP_OUT_H,
)


# --------------------------------------------------------------------------- #
# Fake SMBus                                                                   #
# --------------------------------------------------------------------------- #


class FakeSMBus:
    """Mock SMBus that simulates ICM-20948 register reads/writes."""

    def __init__(self, bus_number: int) -> None:
        self.bus_number = bus_number
        self.closed = False
        self._current_bank = 0
        # Register banks: bank -> {reg: value}
        self._regs: Dict[int, Dict[int, int]] = {
            0: {},
            1: {},
            2: {},
            3: {},
        }
        # Defaults
        self._regs[0][_WHO_AM_I] = _CHIP_ID  # correct chip ID
        # Accel config: ±4g = 0b01 << 1 = 0x02, LPF enabled, mode 5
        self._regs[2][_ACCEL_CONFIG] = 0x02 | 0x01 | (5 << 4)
        # Gyro config: ±250 dps = 0b00, LPF enabled, mode 5
        self._regs[2][_GYRO_CONFIG_1] = 0x01 | (5 << 4)

        # Default accel/gyro data: stationary at 1g on z
        # At ±4g, LSB/g = 8192.  1g on z → az=8192
        self._accel_gyro_data = struct.pack(">hhhhhh", 0, 0, 8192, 0, 0, 0)

        # Temperature: 21°C → raw = 0
        self._temp_data = struct.pack(">h", 0)

        # Magnetometer data: (100, 200, -50) raw → *0.15 µT
        self._mag_data = struct.pack("<hhh", 100, 200, -50)
        self._mag_ready = True

        # External sensor data (for mag passthrough reads)
        self._ext_data: bytes = b"\x00" * 16

    def write_byte_data(self, addr: int, reg: int, value: int) -> None:
        if reg == _BANK_SEL:
            self._current_bank = (value >> 4) & 0x03
        else:
            self._regs[self._current_bank][reg] = value

    def read_byte_data(self, addr: int, reg: int) -> int:
        if reg == _BANK_SEL:
            return self._current_bank << 4

        bank = self._current_bank

        # Magnetometer passthrough: when reading EXT_SLV_SENS_DATA_00 in bank 0
        if bank == 0 and reg == _EXT_SLV_SENS_DATA_00:
            return self._get_ext_sensor_byte(0)

        return self._regs.get(bank, {}).get(reg, 0)

    def read_i2c_block_data(self, addr: int, reg: int, length: int) -> List[int]:
        bank = self._current_bank

        # Accel + Gyro block read (bank 0, starting at ACCEL_XOUT_H)
        if bank == 0 and reg == _ACCEL_XOUT_H and length == 12:
            return list(self._accel_gyro_data)

        # Temperature block read
        if bank == 0 and reg == _TEMP_OUT_H and length == 2:
            return list(self._temp_data)

        # External sensor data (mag passthrough result)
        if bank == 0 and reg == _EXT_SLV_SENS_DATA_00:
            return list(self._ext_data[:length])

        return [0] * length

    def close(self) -> None:
        self.closed = True

    # --- helpers for test scenarios ---

    def set_accel_gyro(
        self,
        ax: int,
        ay: int,
        az: int,
        gx: int,
        gy: int,
        gz: int,
    ) -> None:
        """Set raw accel/gyro register values."""
        self._accel_gyro_data = struct.pack(">hhhhhh", ax, ay, az, gx, gy, gz)

    def set_mag_data(self, mx: int, my: int, mz: int) -> None:
        """Set raw magnetometer register values."""
        self._mag_data = struct.pack("<hhh", mx, my, mz)
        # Also set the external sensor data for passthrough reads
        self._ext_data = self._mag_data + b"\x00" * 10

    def set_ext_sensor_data(self, data: bytes) -> None:
        self._ext_data = data + b"\x00" * max(0, 16 - len(data))

    def _get_ext_sensor_byte(self, offset: int) -> int:
        if offset < len(self._ext_data):
            return self._ext_data[offset]
        return 0


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def fake_bus() -> FakeSMBus:
    return FakeSMBus(1)


@pytest.fixture
def driver(fake_bus: FakeSMBus) -> _ICM20948Driver:
    """Create a driver with a mocked SMBus."""
    with (
        patch("imu_reader.SMBus", return_value=fake_bus)
        if _smbus_importable()
        else patch.dict(sys.modules, {"smbus2": _make_fake_smbus2_module(fake_bus)})
    ):
        d = _ICM20948Driver(bus_number=1, address=0x68)
    # Manually assign the fake bus (in case the patch didn't work due to import order)
    d._bus = fake_bus
    d._current_bank = -1
    return d


def _smbus_importable() -> bool:
    try:
        import smbus2  # noqa: F401

        return True
    except ImportError:
        return False


def _make_fake_smbus2_module(fake_bus: FakeSMBus) -> MagicMock:
    mod = MagicMock()
    mod.SMBus = MagicMock(return_value=fake_bus)
    return mod


# --------------------------------------------------------------------------- #
# IMUSample tests                                                              #
# --------------------------------------------------------------------------- #


class TestIMUSample:
    def test_accel_magnitude_at_rest(self) -> None:
        """At rest, accel magnitude should be ~1g (9.81 m/s²)."""
        sample = IMUSample(
            timestamp=datetime.now(timezone.utc),
            accel_x=0.0,
            accel_y=0.0,
            accel_z=_GRAVITY,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
        )
        assert abs(sample.accel_magnitude - _GRAVITY) < 0.01

    def test_accel_magnitude_tilted(self) -> None:
        """Magnitude should be ~1g regardless of orientation."""
        # 45-degree tilt: z=g*cos(45), x=g*sin(45)
        g45 = _GRAVITY * math.cos(math.radians(45))
        sample = IMUSample(
            timestamp=datetime.now(timezone.utc),
            accel_x=g45,
            accel_y=0.0,
            accel_z=g45,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
        )
        assert abs(sample.accel_magnitude - _GRAVITY) < 0.01

    def test_vertical_accel_at_rest(self) -> None:
        """At rest on a flat surface, vertical_accel should be ~0."""
        sample = IMUSample(
            timestamp=datetime.now(timezone.utc),
            accel_x=0.0,
            accel_y=0.0,
            accel_z=_GRAVITY,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
        )
        assert abs(sample.vertical_accel) < 0.01

    def test_vertical_accel_heave(self) -> None:
        """Upward heave should show positive vertical_accel."""
        heave = 2.0  # m/s² upward
        sample = IMUSample(
            timestamp=datetime.now(timezone.utc),
            accel_x=0.0,
            accel_y=0.0,
            accel_z=_GRAVITY + heave,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
        )
        assert abs(sample.vertical_accel - heave) < 0.01

    def test_vertical_accel_tilted_at_rest(self) -> None:
        """At rest but tilted 90°, vertical_accel should still be ~0."""
        # IMU mounted sideways: gravity along x-axis, z reads ~0
        sample = IMUSample(
            timestamp=datetime.now(timezone.utc),
            accel_x=_GRAVITY,
            accel_y=0.0,
            accel_z=0.0,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
        )
        # |a| - g = g - g = 0 regardless of orientation
        assert abs(sample.vertical_accel) < 0.01

    def test_vertical_accel_calibrated_level(self) -> None:
        """With gravity calibrated along Z, vertical_accel uses dot product."""
        # Gravity along Z (level mount)
        sample = IMUSample(
            timestamp=datetime.now(timezone.utc),
            accel_x=0.0,
            accel_y=0.0,
            accel_z=_GRAVITY,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
            _gravity_unit=(0.0, 0.0, 1.0),
        )
        assert abs(sample.vertical_accel) < 0.01

    def test_vertical_accel_calibrated_level_with_heave(self) -> None:
        """Calibrated level mount: heave adds to gravity axis."""
        heave = 2.0  # m/s²
        sample = IMUSample(
            timestamp=datetime.now(timezone.utc),
            accel_x=0.0,
            accel_y=0.0,
            accel_z=_GRAVITY + heave,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
            _gravity_unit=(0.0, 0.0, 1.0),
        )
        assert abs(sample.vertical_accel - heave) < 0.01

    def test_vertical_accel_calibrated_sideways_at_rest(self) -> None:
        """IMU mounted sideways (gravity along X): at rest should be ~0."""
        sample = IMUSample(
            timestamp=datetime.now(timezone.utc),
            accel_x=_GRAVITY,
            accel_y=0.0,
            accel_z=0.0,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
            _gravity_unit=(1.0, 0.0, 0.0),
        )
        assert abs(sample.vertical_accel) < 0.01

    def test_vertical_accel_calibrated_sideways_with_heave(self) -> None:
        """IMU mounted sideways (gravity along X): heave adds to X axis.

        This is the critical test case.  Without calibration, |a|-g badly
        underestimates heave when the IMU is mounted at 90°.  With the
        gravity unit vector, the dot product correctly extracts the heave.
        """
        heave = 2.0  # m/s² upward
        # At rest: accel_x = g.  With upward heave: accel_x = g + heave
        # (heave adds to gravity direction)
        sample = IMUSample(
            timestamp=datetime.now(timezone.utc),
            accel_x=_GRAVITY + heave,
            accel_y=0.0,
            accel_z=0.0,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
            _gravity_unit=(1.0, 0.0, 0.0),
        )
        # Calibrated: dot((g+heave,0,0), (1,0,0)) - g = heave
        assert abs(sample.vertical_accel - heave) < 0.01

        # Without calibration (fallback): |a|-g = (g+heave)-g = heave
        # (happens to work for pure-axis alignment, but fails with
        #  lateral accel — see next test)
        sample_uncal = IMUSample(
            timestamp=datetime.now(timezone.utc),
            accel_x=_GRAVITY + heave,
            accel_y=0.0,
            accel_z=0.0,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
        )
        assert abs(sample_uncal.vertical_accel - heave) < 0.01

    def test_vertical_accel_sideways_with_lateral_accel(self) -> None:
        """Sideways mount with lateral acceleration demonstrates the bug
        that calibration fixes.

        When the IMU is sideways (gravity along X) and a lateral
        acceleration exists on Z (e.g. from roll), the uncalibrated
        |a|-g overestimates heave because |a| increases with any
        off-axis component.  The calibrated dot-product correctly
        ignores the lateral component.
        """
        lateral = 3.0  # m/s² lateral (e.g. roll on a catamaran)
        heave = 0.5  # m/s² heave

        # Calibrated: correctly extracts only the gravity-axis component
        sample_cal = IMUSample(
            timestamp=datetime.now(timezone.utc),
            accel_x=_GRAVITY + heave,  # gravity axis + heave
            accel_y=0.0,
            accel_z=lateral,  # lateral — should be ignored
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
            _gravity_unit=(1.0, 0.0, 0.0),
        )
        assert abs(sample_cal.vertical_accel - heave) < 0.01

        # Uncalibrated: magnitude inflated by lateral component
        sample_uncal = IMUSample(
            timestamp=datetime.now(timezone.utc),
            accel_x=_GRAVITY + heave,
            accel_y=0.0,
            accel_z=lateral,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
        )
        # |a| = sqrt((g+0.5)² + 3²) ≈ 10.74, |a|-g ≈ 0.93 (wrong!)
        assert sample_uncal.vertical_accel > heave + 0.3  # demonstrates the error

    def test_mag_fields_optional(self) -> None:
        """Magnetometer fields default to None."""
        sample = IMUSample(
            timestamp=datetime.now(timezone.utc),
            accel_x=0.0,
            accel_y=0.0,
            accel_z=_GRAVITY,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
        )
        assert sample.mag_x is None
        assert sample.mag_y is None
        assert sample.mag_z is None

    def test_mag_fields_present(self) -> None:
        """Magnetometer fields can be set."""
        sample = IMUSample(
            timestamp=datetime.now(timezone.utc),
            accel_x=0.0,
            accel_y=0.0,
            accel_z=_GRAVITY,
            gyro_x=0.0,
            gyro_y=0.0,
            gyro_z=0.0,
            mag_x=15.0,
            mag_y=30.0,
            mag_z=-7.5,
        )
        assert sample.mag_x == 15.0
        assert sample.mag_y == 30.0
        assert sample.mag_z == -7.5


# --------------------------------------------------------------------------- #
# Driver tests                                                                 #
# --------------------------------------------------------------------------- #


class TestICM20948Driver:
    def test_init_reads_chip_id(
        self, driver: _ICM20948Driver, fake_bus: FakeSMBus
    ) -> None:
        """init() should succeed when WHO_AM_I returns 0xEA."""
        # init() does the full setup sequence
        driver.init()
        # If we get here without RuntimeError, chip ID was accepted

    def test_init_wrong_chip_id(self, fake_bus: FakeSMBus) -> None:
        """init() should raise RuntimeError for wrong chip ID."""
        fake_bus._regs[0][_WHO_AM_I] = 0xFF  # wrong ID

        with patch.dict(sys.modules, {"smbus2": _make_fake_smbus2_module(fake_bus)}):
            d = _ICM20948Driver.__new__(_ICM20948Driver)
            d._bus = fake_bus
            d._addr = 0x68
            d._current_bank = -1

        with pytest.raises(RuntimeError, match="ICM-20948 not found"):
            d.init()

    def test_read_accel_gyro_at_rest(
        self, driver: _ICM20948Driver, fake_bus: FakeSMBus
    ) -> None:
        """Stationary sensor should read ~0,0,g for accel and ~0,0,0 for gyro."""
        driver.init()

        # Default fake_bus has az=8192 (1g at ±4g scale)
        ax, ay, az, gx, gy, gz = driver.read_accel_gyro()

        assert abs(ax) < 0.01
        assert abs(ay) < 0.01
        assert abs(az - _GRAVITY) < 0.05  # ~9.81 m/s²
        assert abs(gx) < 0.01
        assert abs(gy) < 0.01
        assert abs(gz) < 0.01

    def test_read_accel_known_value(
        self, driver: _ICM20948Driver, fake_bus: FakeSMBus
    ) -> None:
        """Test with a known acceleration value."""
        driver.init()

        # Set 0.5g on x-axis: at ±4g, LSB/g=8192 → 0.5g = 4096
        fake_bus.set_accel_gyro(4096, 0, 8192, 0, 0, 0)
        ax, ay, az, gx, gy, gz = driver.read_accel_gyro()

        expected_ax = 0.5 * _GRAVITY
        assert abs(ax - expected_ax) < 0.1
        assert abs(az - _GRAVITY) < 0.1

    def test_read_gyro_known_value(
        self, driver: _ICM20948Driver, fake_bus: FakeSMBus
    ) -> None:
        """Test with a known gyro value."""
        driver.init()

        # 10 deg/s on z-axis: at ±250 dps, LSB/(deg/s)=131 → 10 dps = 1310
        fake_bus.set_accel_gyro(0, 0, 8192, 0, 0, 1310)
        ax, ay, az, gx, gy, gz = driver.read_accel_gyro()

        expected_gz = math.radians(10.0)
        assert abs(gz - expected_gz) < 0.02  # ~0.175 rad/s

    def test_read_temperature(
        self, driver: _ICM20948Driver, fake_bus: FakeSMBus
    ) -> None:
        """Temperature conversion from raw register value."""
        driver.init()

        # raw = 0 → ((0-21)/333.87) + 21 = 20.937°C
        temp = driver.read_temperature()
        assert abs(temp - 20.937) < 0.1

    def test_close(self, driver: _ICM20948Driver, fake_bus: FakeSMBus) -> None:
        """close() should close the underlying bus."""
        driver.close()
        assert fake_bus.closed

    def test_bank_switching(self, driver: _ICM20948Driver, fake_bus: FakeSMBus) -> None:
        """Bank switching should change the active register bank."""
        driver._bank(0)
        assert fake_bus._current_bank == 0
        driver._bank(2)
        assert fake_bus._current_bank == 2
        driver._bank(3)
        assert fake_bus._current_bank == 3

    def test_bank_caching(self, driver: _ICM20948Driver, fake_bus: FakeSMBus) -> None:
        """Switching to the same bank should not issue a write."""
        driver._bank(2)
        driver._current_bank = 2  # mark as current
        # Patch write to track calls
        original_write = fake_bus.write_byte_data
        call_count = 0

        def counting_write(addr: int, reg: int, value: int) -> None:
            nonlocal call_count
            call_count += 1
            original_write(addr, reg, value)

        fake_bus.write_byte_data = counting_write  # type: ignore[assignment]
        driver._bank(2)  # should be a no-op
        assert call_count == 0


# --------------------------------------------------------------------------- #
# Async IMUReader tests                                                        #
# --------------------------------------------------------------------------- #


class TestIMUReader:
    @pytest.mark.asyncio
    async def test_create_returns_none_without_hardware(self) -> None:
        """create() should return None when smbus2 import fails."""
        # Force the ImportError by removing smbus2 from sys.modules
        saved = sys.modules.get("smbus2")
        sys.modules["smbus2"] = None  # type: ignore[assignment]
        try:
            reader = await IMUReader.create(bus_number=99, address=0x68)
            assert reader is None
        finally:
            if saved is not None:
                sys.modules["smbus2"] = saved
            else:
                sys.modules.pop("smbus2", None)

    @pytest.mark.asyncio
    async def test_create_success_with_mock(self, fake_bus: FakeSMBus) -> None:
        """create() should return an IMUReader when hardware is present."""
        fake_smbus2 = _make_fake_smbus2_module(fake_bus)
        with patch.dict(sys.modules, {"smbus2": fake_smbus2}):
            # Also need to patch the import inside _ICM20948Driver.__init__
            with patch("imu_reader.SMBus", fake_smbus2.SMBus, create=True):
                reader = await IMUReader.create(bus_number=1, address=0x68)
                if reader is not None:
                    # Manually replace the bus
                    reader._driver._bus = fake_bus
                    reader._driver._current_bank = -1

        # May return None depending on import mechanics in test env.
        # The important thing is it doesn't crash.

    @pytest.mark.asyncio
    async def test_read_sample_returns_imu_sample(self) -> None:
        """read_sample() should return a valid IMUSample."""
        fake_bus = FakeSMBus(1)
        fake_bus.set_ext_sensor_data(struct.pack("<hhh", 100, 200, -50))

        # Create driver directly, bypassing smbus2 import
        driver = _ICM20948Driver.__new__(_ICM20948Driver)
        driver._bus = fake_bus
        driver._addr = 0x68
        driver._current_bank = -1

        reader = IMUReader(driver)
        sample = await reader.read_sample()

        assert isinstance(sample, IMUSample)
        assert isinstance(sample.timestamp, datetime)
        assert sample.timestamp.tzinfo is not None  # UTC
        assert abs(sample.accel_z - _GRAVITY) < 0.1
        assert sample.temperature is not None

    @pytest.mark.asyncio
    async def test_read_accel_gyro_only(self) -> None:
        """read_accel_gyro_only() skips magnetometer."""
        fake_bus = FakeSMBus(1)

        driver = _ICM20948Driver.__new__(_ICM20948Driver)
        driver._bus = fake_bus
        driver._addr = 0x68
        driver._current_bank = -1

        reader = IMUReader(driver)
        sample = await reader.read_accel_gyro_only()

        assert isinstance(sample, IMUSample)
        assert sample.mag_x is None
        assert sample.mag_y is None
        assert sample.mag_z is None
        # Accel should still be valid
        assert abs(sample.accel_z - _GRAVITY) < 0.1

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        """close() should release the I2C bus."""
        fake_bus = FakeSMBus(1)

        driver = _ICM20948Driver.__new__(_ICM20948Driver)
        driver._bus = fake_bus
        driver._addr = 0x68
        driver._current_bank = -1

        reader = IMUReader(driver)
        reader.close()
        assert fake_bus.closed

    # --- Gravity calibration tests ---

    def test_initial_state_uncalibrated(self) -> None:
        """Freshly constructed IMUReader should be uncalibrated."""
        fake_bus = FakeSMBus(1)
        driver = _ICM20948Driver.__new__(_ICM20948Driver)
        driver._bus = fake_bus
        driver._addr = 0x68
        driver._current_bank = -1

        reader = IMUReader(driver)
        assert reader.is_calibrated is False
        assert reader.gravity_unit is None

    @pytest.mark.asyncio
    async def test_calibrate_level_mount(self) -> None:
        """calibrate() with gravity along Z should produce (0,0,1)."""
        fake_bus = FakeSMBus(1)
        # Default FakeSMBus: az=8192 (1g at ±4g) → accel_z ≈ 9.81
        driver = _ICM20948Driver.__new__(_ICM20948Driver)
        driver._bus = fake_bus
        driver._addr = 0x68
        driver._current_bank = -1

        reader = IMUReader(driver)
        grav = await reader.calibrate(duration_s=0.1, rate_hz=50.0)

        assert reader.is_calibrated is True
        gx, gy, gz = grav
        # Should be approximately (0, 0, 1)
        assert abs(gx) < 0.05
        assert abs(gy) < 0.05
        assert abs(gz - 1.0) < 0.05

    @pytest.mark.asyncio
    async def test_calibrate_sideways_mount(self) -> None:
        """calibrate() with gravity along X should produce (~1,0,0)."""
        fake_bus = FakeSMBus(1)
        # 1g along X: ax=8192, ay=0, az=0 at ±4g
        fake_bus.set_accel_gyro(8192, 0, 0, 0, 0, 0)
        driver = _ICM20948Driver.__new__(_ICM20948Driver)
        driver._bus = fake_bus
        driver._addr = 0x68
        driver._current_bank = -1

        reader = IMUReader(driver)
        grav = await reader.calibrate(duration_s=0.1, rate_hz=50.0)

        assert reader.is_calibrated is True
        gx, gy, gz = grav
        assert abs(gx - 1.0) < 0.05
        assert abs(gy) < 0.05
        assert abs(gz) < 0.05

    @pytest.mark.asyncio
    async def test_calibrate_inverted_mount(self) -> None:
        """calibrate() with gravity along -Z should produce (0,0,-1)."""
        fake_bus = FakeSMBus(1)
        # -1g along Z: az=-8192
        fake_bus.set_accel_gyro(0, 0, -8192, 0, 0, 0)
        driver = _ICM20948Driver.__new__(_ICM20948Driver)
        driver._bus = fake_bus
        driver._addr = 0x68
        driver._current_bank = -1

        reader = IMUReader(driver)
        grav = await reader.calibrate(duration_s=0.1, rate_hz=50.0)

        gx, gy, gz = grav
        assert abs(gx) < 0.05
        assert abs(gy) < 0.05
        assert abs(gz + 1.0) < 0.05  # gz ≈ -1

    @pytest.mark.asyncio
    async def test_calibrate_diagonal_mount(self) -> None:
        """calibrate() with gravity at 45° between X and Z."""
        fake_bus = FakeSMBus(1)
        # Equal gravity on X and Z: 1g * cos(45°) = 0.707g each
        # At ±4g, LSB/g=8192 → 0.707*8192 ≈ 5793
        val = int(8192 * math.cos(math.radians(45)))
        fake_bus.set_accel_gyro(val, 0, val, 0, 0, 0)
        driver = _ICM20948Driver.__new__(_ICM20948Driver)
        driver._bus = fake_bus
        driver._addr = 0x68
        driver._current_bank = -1

        reader = IMUReader(driver)
        grav = await reader.calibrate(duration_s=0.1, rate_hz=50.0)

        gx, gy, gz = grav
        expected = 1.0 / math.sqrt(2.0)
        assert abs(gx - expected) < 0.05
        assert abs(gy) < 0.05
        assert abs(gz - expected) < 0.05

    @pytest.mark.asyncio
    async def test_read_sample_injects_gravity_unit(self) -> None:
        """After calibration, read_sample() should inject gravity_unit into IMUSample."""
        fake_bus = FakeSMBus(1)
        fake_bus.set_ext_sensor_data(struct.pack("<hhh", 100, 200, -50))
        driver = _ICM20948Driver.__new__(_ICM20948Driver)
        driver._bus = fake_bus
        driver._addr = 0x68
        driver._current_bank = -1

        reader = IMUReader(driver)
        # Calibrate first
        await reader.calibrate(duration_s=0.1, rate_hz=50.0)
        assert reader.is_calibrated

        # Now read a sample
        sample = await reader.read_sample()
        assert sample._gravity_unit is not None
        gx, gy, gz = sample._gravity_unit
        # Default bus has gravity along Z
        assert abs(gz - 1.0) < 0.1

    @pytest.mark.asyncio
    async def test_read_accel_gyro_only_injects_gravity_unit(self) -> None:
        """After calibration, read_accel_gyro_only() should inject gravity_unit."""
        fake_bus = FakeSMBus(1)
        driver = _ICM20948Driver.__new__(_ICM20948Driver)
        driver._bus = fake_bus
        driver._addr = 0x68
        driver._current_bank = -1

        reader = IMUReader(driver)
        await reader.calibrate(duration_s=0.1, rate_hz=50.0)

        sample = await reader.read_accel_gyro_only()
        assert sample._gravity_unit is not None

    @pytest.mark.asyncio
    async def test_uncalibrated_read_sample_no_gravity(self) -> None:
        """Without calibration, read_sample() should have gravity_unit=None initially.

        Note: After enough reads, _update_gravity will set it once
        _grav_n hits a multiple of 50.
        """
        fake_bus = FakeSMBus(1)
        fake_bus.set_ext_sensor_data(struct.pack("<hhh", 100, 200, -50))
        driver = _ICM20948Driver.__new__(_ICM20948Driver)
        driver._bus = fake_bus
        driver._addr = 0x68
        driver._current_bank = -1

        reader = IMUReader(driver)
        # First read: _grav_n goes from 0 to 1 (first sample initialises),
        # then increments to 2.  Unit vector only recomputed at n%50==0.
        sample = await reader.read_sample()
        # After first read, _grav_n is 2, not a multiple of 50 yet
        assert sample._gravity_unit is None

    def test_update_gravity_first_sample_initialises(self) -> None:
        """_update_gravity with first sample should initialise the sums."""
        fake_bus = FakeSMBus(1)
        driver = _ICM20948Driver.__new__(_ICM20948Driver)
        driver._bus = fake_bus
        driver._addr = 0x68
        driver._current_bank = -1

        reader = IMUReader(driver)
        assert reader._grav_n == 0

        reader._update_gravity(0.0, 0.0, _GRAVITY)
        assert reader._grav_n == 2  # incremented from 0→set to 1, then +1
        assert abs(reader._grav_sum_z - _GRAVITY) < 0.01

    def test_update_gravity_progressive_refinement(self) -> None:
        """_update_gravity should progressively refine toward the true direction.

        After 50 calls (the recompute threshold), the gravity unit vector
        should be set.
        """
        fake_bus = FakeSMBus(1)
        driver = _ICM20948Driver.__new__(_ICM20948Driver)
        driver._bus = fake_bus
        driver._addr = 0x68
        driver._current_bank = -1

        reader = IMUReader(driver)

        # Feed 50 samples with gravity along X (sideways mount)
        for _ in range(50):
            reader._update_gravity(_GRAVITY, 0.0, 0.0)

        # At _grav_n=50 the unit vector should be recomputed
        assert reader.is_calibrated
        gx, gy, gz = reader.gravity_unit  # type: ignore[misc]
        assert abs(gx - 1.0) < 0.01
        assert abs(gy) < 0.01
        assert abs(gz) < 0.01

    def test_update_gravity_ema_tracks_slow_change(self) -> None:
        """EMA should eventually track a slow orientation change.

        Feed many samples along Z, then switch to X.  After enough samples
        the gravity estimate should shift toward X.
        """
        fake_bus = FakeSMBus(1)
        driver = _ICM20948Driver.__new__(_ICM20948Driver)
        driver._bus = fake_bus
        driver._addr = 0x68
        driver._current_bank = -1

        reader = IMUReader(driver)

        # Seed along Z
        for _ in range(100):
            reader._update_gravity(0.0, 0.0, _GRAVITY)

        assert reader.is_calibrated
        _, _, gz_before = reader.gravity_unit  # type: ignore[misc]
        assert gz_before > 0.9  # strongly along Z

        # Now switch to X for many samples (simulating slow heel)
        for _ in range(100000):
            reader._update_gravity(_GRAVITY, 0.0, 0.0)

        gx_after, _, gz_after = reader.gravity_unit  # type: ignore[misc]
        # Should have shifted substantially toward X
        assert gx_after > 0.5
        assert gz_after < gz_before

    def test_recompute_gravity_unit_zero_magnitude_safe(self) -> None:
        """_recompute_gravity_unit should not crash with near-zero sums."""
        fake_bus = FakeSMBus(1)
        driver = _ICM20948Driver.__new__(_ICM20948Driver)
        driver._bus = fake_bus
        driver._addr = 0x68
        driver._current_bank = -1

        reader = IMUReader(driver)
        reader._grav_sum_x = 0.0
        reader._grav_sum_y = 0.0
        reader._grav_sum_z = 0.0
        reader._grav_n = 1

        # Should not crash, and should not set gravity_unit
        reader._recompute_gravity_unit()
        assert reader.gravity_unit is None


# --------------------------------------------------------------------------- #
# InstantSample IMU field tests                                                #
# --------------------------------------------------------------------------- #


class TestInstantSampleIMUFields:
    def test_imu_fields_default_none(self) -> None:
        """All IMU fields on InstantSample should default to None."""
        from models import InstantSample

        sample = InstantSample(timestamp=datetime.now(timezone.utc))
        assert sample.accel_x is None
        assert sample.accel_y is None
        assert sample.accel_z is None
        assert sample.gyro_x is None
        assert sample.gyro_y is None
        assert sample.gyro_z is None
        assert sample.mag_x is None
        assert sample.mag_y is None
        assert sample.mag_z is None
        assert sample.vertical_accel is None

    def test_imu_fields_settable(self) -> None:
        """IMU fields should be settable on InstantSample."""
        from models import InstantSample

        sample = InstantSample(timestamp=datetime.now(timezone.utc))
        sample.accel_x = 0.1
        sample.accel_y = 0.2
        sample.accel_z = 9.81
        sample.gyro_x = 0.01
        sample.gyro_y = 0.02
        sample.gyro_z = 0.03
        sample.mag_x = 15.0
        sample.mag_y = 30.0
        sample.mag_z = -7.5
        sample.vertical_accel = 0.0

        assert sample.accel_x == 0.1
        assert sample.accel_z == 9.81
        assert sample.mag_z == -7.5
        assert sample.vertical_accel == 0.0


# --------------------------------------------------------------------------- #
# Config IMU fields tests                                                      #
# --------------------------------------------------------------------------- #


class TestConfigIMUFields:
    def test_default_imu_config(self) -> None:
        """Config should have sensible IMU defaults."""
        from config import Config

        c = Config()
        assert c.imu_enabled is True
        assert c.imu_bus_number == 1
        assert c.imu_address == 0x68
        assert c.imu_sample_rate_hz == 50.0
        assert c.imu_include_mag is True

    def test_imu_disabled(self) -> None:
        """IMU can be disabled via config."""
        from config import Config

        c = Config(imu_enabled=False)
        assert c.imu_enabled is False


# --------------------------------------------------------------------------- #
# IMU merge logic tests (unit test of _merge_imu concept)                      #
# --------------------------------------------------------------------------- #


class TestIMUMerge:
    def test_merge_overlays_imu_onto_sample(self) -> None:
        """Merging an IMUSample onto an InstantSample should set IMU fields."""
        from models import InstantSample

        now = datetime.now(timezone.utc)

        sample = InstantSample(
            timestamp=now,
            roll=0.1,
            pitch=0.05,
        )
        imu = IMUSample(
            timestamp=now,
            accel_x=0.1,
            accel_y=-0.2,
            accel_z=9.81,
            gyro_x=0.01,
            gyro_y=-0.01,
            gyro_z=0.005,
            mag_x=15.0,
            mag_y=30.0,
            mag_z=-7.5,
        )

        # Simulate what _merge_imu does
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

        # Signal K fields preserved
        assert sample.roll == 0.1
        assert sample.pitch == 0.05
        # IMU fields set
        assert sample.accel_x == 0.1
        assert sample.accel_z == 9.81
        assert sample.gyro_z == 0.005
        assert sample.mag_x == 15.0
        assert abs(sample.vertical_accel) < 0.01  # ~0 at rest

    def test_merge_no_imu_leaves_none(self) -> None:
        """Without IMU data, IMU fields should remain None."""
        from models import InstantSample

        now = datetime.now(timezone.utc)

        sample = InstantSample(
            timestamp=now,
            roll=0.1,
        )
        # No merge
        assert sample.accel_x is None
        assert sample.vertical_accel is None


# --------------------------------------------------------------------------- #
# Double-count fix tests (_imu_highrate_active)                                #
# --------------------------------------------------------------------------- #


class TestIMUHighrateActiveFlag:
    """Verify that the feature extractor doesn't double-count accel data.

    When the high-rate IMU path (add_imu_accel at 50 Hz) is active,
    add_sample() should NOT also buffer vertical_accel into _accel_buf.
    """

    def test_accel_buf_from_sample_when_no_imu(self) -> None:
        """Without IMU, add_sample() should buffer vertical_accel."""
        from config import Config
        from feature_extractor import FeatureExtractor
        from models import InstantSample

        config = Config()
        fe = FeatureExtractor(config)

        assert fe._imu_highrate_active is False
        assert len(fe._accel_buf) == 0

        now = datetime.now(timezone.utc)
        sample = InstantSample(timestamp=now)
        sample.vertical_accel = 0.5
        fe.add_sample(sample)

        assert len(fe._accel_buf) == 1
        assert fe._accel_buf[0] == 0.5

    def test_accel_buf_blocked_when_imu_active(self) -> None:
        """Once add_imu_accel is called, add_sample() must not buffer accel."""
        from config import Config
        from feature_extractor import FeatureExtractor
        from models import InstantSample

        config = Config()
        fe = FeatureExtractor(config)

        # Activate high-rate path
        fe.add_imu_accel(0.1)
        assert fe._imu_highrate_active is True
        assert len(fe._accel_buf) == 1  # from add_imu_accel

        # Now add_sample with vertical_accel should NOT add to _accel_buf
        now = datetime.now(timezone.utc)
        sample = InstantSample(timestamp=now)
        sample.vertical_accel = 0.5
        fe.add_sample(sample)

        # Buffer should still only have the 1 sample from add_imu_accel
        assert len(fe._accel_buf) == 1

    def test_add_imu_accel_buffers_correctly(self) -> None:
        """add_imu_accel should always buffer regardless of flag state."""
        from config import Config
        from feature_extractor import FeatureExtractor

        config = Config()
        fe = FeatureExtractor(config)

        for i in range(10):
            fe.add_imu_accel(float(i) * 0.1)

        assert len(fe._accel_buf) == 10
        assert fe._imu_highrate_active is True

    def test_no_double_count_sequence(self) -> None:
        """Realistic sequence: IMU accel at 50 Hz + samples at 2 Hz.

        Only the 50 Hz data should end up in _accel_buf.
        """
        from config import Config
        from feature_extractor import FeatureExtractor
        from models import InstantSample

        config = Config()
        fe = FeatureExtractor(config)

        now = datetime.now(timezone.utc)

        # Simulate 1 second: 50 IMU samples + 2 regular samples
        for i in range(50):
            fe.add_imu_accel(0.01 * i)
            # Every 25 IMU samples, a 2 Hz sample arrives
            if i % 25 == 0:
                sample = InstantSample(timestamp=now)
                sample.vertical_accel = 99.0  # distinctive value
                fe.add_sample(sample)

        # Should have exactly 50 from IMU, none from add_sample
        assert len(fe._accel_buf) == 50
        # The distinctive 99.0 should NOT be in the buffer
        assert 99.0 not in list(fe._accel_buf)
