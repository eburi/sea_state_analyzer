"""IMU reader over I2C with auto-detection.

Reads accelerometer (g), gyroscope (deg/s), magnetometer (µT), and
temperature (°C) from supported IMU chips (currently ICM-20948) via smbus2.

When auto-detection is enabled the reader probes the I2C bus for known
chips (see imu_registry.py / imu_detect.py) before attempting init.

Design goals:
- Self-contained: no dependency beyond smbus2 (standard on Pi)
- Async-friendly: blocking I2C reads are run in a thread executor
- Graceful absence: ``IMUReader.create()`` returns None when hardware
  is unavailable, so the rest of the pipeline runs unaffected on Mac.

Typical usage::

    reader = await IMUReader.create(bus_number=1, auto_detect=True)
    if reader is not None:
        sample = await reader.read_sample()
        print(sample)
"""

from __future__ import annotations

import asyncio
import logging
import math
import struct
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# ICM-20948 register map (simplified to what we need)                          #
# --------------------------------------------------------------------------- #

_CHIP_ID = 0xEA
_I2C_ADDR = 0x68
_BANK_SEL = 0x7F

# Bank 0
_WHO_AM_I = 0x00
_USER_CTRL = 0x03
_PWR_MGMT_1 = 0x06
_PWR_MGMT_2 = 0x07
_INT_PIN_CFG = 0x0F
_ACCEL_XOUT_H = 0x2D
_GYRO_XOUT_H = 0x33
_TEMP_OUT_H = 0x39
_EXT_SLV_SENS_DATA_00 = 0x3B

# Bank 2
_ACCEL_SMPLRT_DIV_1 = 0x10
_ACCEL_SMPLRT_DIV_2 = 0x11
_ACCEL_CONFIG = 0x14
_GYRO_SMPLRT_DIV = 0x00
_GYRO_CONFIG_1 = 0x01

# Bank 3 – I2C master for magnetometer
_I2C_MST_CTRL = 0x01
_I2C_MST_DELAY_CTRL = 0x02
_I2C_SLV0_ADDR = 0x03
_I2C_SLV0_REG = 0x04
_I2C_SLV0_CTRL = 0x05
_I2C_SLV0_DO = 0x06

# AK09916 magnetometer (accessible via I2C master passthrough)
_AK09916_ADDR = 0x0C
_AK09916_CHIP_ID = 0x09
_AK09916_WIA = 0x01
_AK09916_ST1 = 0x10
_AK09916_HXL = 0x11
_AK09916_CNTL2 = 0x31
_AK09916_CNTL3 = 0x32

# Temperature conversion
_TEMP_OFFSET = 21
_TEMP_SENSITIVITY = 333.87

# Gravity constant for converting accelerometer to m/s²
_GRAVITY = 9.80665


# --------------------------------------------------------------------------- #
# Data structures                                                              #
# --------------------------------------------------------------------------- #


@dataclass
class IMUSample:
    """A single timestamped reading from the ICM-20948."""

    timestamp: datetime

    # Accelerometer (m/s²) — IMU body frame
    accel_x: float
    accel_y: float
    accel_z: float

    # Gyroscope (rad/s)
    gyro_x: float
    gyro_y: float
    gyro_z: float

    # Magnetometer (µT) — may be None if read timed out
    mag_x: Optional[float] = None
    mag_y: Optional[float] = None
    mag_z: Optional[float] = None

    # Die temperature (°C)
    temperature: Optional[float] = None

    # Gravity unit vector in IMU body frame (set by calibration).
    # When None, vertical_accel falls back to the |a|-g approximation.
    _gravity_unit: Optional[Tuple[float, float, float]] = None

    @property
    def accel_magnitude(self) -> float:
        """Total acceleration magnitude in m/s²."""
        return math.sqrt(self.accel_x**2 + self.accel_y**2 + self.accel_z**2)

    @property
    def vertical_accel(self) -> float:
        """Vertical (heave) acceleration component in m/s².

        When a calibrated gravity unit vector is available (from startup
        calibration), this projects the accelerometer vector onto the
        gravity direction and subtracts g::

            vertical_accel = dot(accel, gravity_unit) - g

        This works correctly regardless of IMU mounting orientation —
        even when the IMU is mounted sideways or upside-down.

        Without calibration, falls back to ``|a| - g`` which is only
        accurate when lateral accelerations are small relative to g.
        """
        if self._gravity_unit is not None:
            gx, gy, gz = self._gravity_unit
            # Dot product of accel vector with gravity unit vector
            # gives the component along Earth's vertical axis.
            # Positive = upward (away from gravity), so we negate
            # the dot product (gravity points down, accel at rest
            # points up) — actually, at rest accel = +g along gravity
            # direction, so dot(accel, grav_unit) = +g at rest.
            return (
                self.accel_x * gx + self.accel_y * gy + self.accel_z * gz
            ) - _GRAVITY
        return self.accel_magnitude - _GRAVITY


# --------------------------------------------------------------------------- #
# Low-level synchronous driver                                                 #
# --------------------------------------------------------------------------- #


class _ICM20948Driver:
    """Thin synchronous driver for ICM-20948 over smbus2.

    Based on the Pimoroni reference driver but stripped to essentials.
    All methods are blocking and NOT thread-safe — the async wrapper
    serialises access.
    """

    def __init__(self, bus_number: int = 1, address: int = _I2C_ADDR) -> None:
        from smbus2 import SMBus

        self._bus = SMBus(bus_number)
        self._addr = address
        self._current_bank = -1

    def close(self) -> None:
        self._bus.close()

    # --- Register access -------------------------------------------------- #

    def _write(self, reg: int, value: int) -> None:
        self._bus.write_byte_data(self._addr, reg, value)
        time.sleep(0.0001)

    def _read(self, reg: int) -> int:
        return self._bus.read_byte_data(self._addr, reg)

    def _read_bytes(self, reg: int, length: int) -> bytes:
        return bytes(self._bus.read_i2c_block_data(self._addr, reg, length))

    def _bank(self, bank: int) -> None:
        if self._current_bank != bank:
            self._write(_BANK_SEL, bank << 4)
            self._current_bank = bank

    # --- Magnetometer passthrough ----------------------------------------- #

    def _trigger_mag_io(self) -> None:
        user = self._read(_USER_CTRL)
        self._write(_USER_CTRL, user | 0x20)
        time.sleep(0.005)
        self._write(_USER_CTRL, user)

    def _mag_write(self, reg: int, value: int) -> None:
        self._bank(3)
        self._write(_I2C_SLV0_ADDR, _AK09916_ADDR)
        self._write(_I2C_SLV0_REG, reg)
        self._write(_I2C_SLV0_DO, value)
        self._bank(0)
        self._trigger_mag_io()

    def _mag_read(self, reg: int) -> int:
        self._bank(3)
        self._write(_I2C_SLV0_ADDR, _AK09916_ADDR | 0x80)
        self._write(_I2C_SLV0_REG, reg)
        self._write(_I2C_SLV0_DO, 0xFF)
        self._write(_I2C_SLV0_CTRL, 0x80 | 1)
        self._bank(0)
        self._trigger_mag_io()
        return self._read(_EXT_SLV_SENS_DATA_00)

    def _mag_read_bytes(self, reg: int, length: int) -> bytes:
        self._bank(3)
        self._write(_I2C_SLV0_CTRL, 0x80 | 0x08 | length)
        self._write(_I2C_SLV0_ADDR, _AK09916_ADDR | 0x80)
        self._write(_I2C_SLV0_REG, reg)
        self._write(_I2C_SLV0_DO, 0xFF)
        self._bank(0)
        self._trigger_mag_io()
        return self._read_bytes(_EXT_SLV_SENS_DATA_00, length)

    # --- Initialisation --------------------------------------------------- #

    def init(self) -> None:
        """Reset and configure the ICM-20948 + AK09916."""
        self._bank(0)
        chip_id = self._read(_WHO_AM_I)
        if chip_id != _CHIP_ID:
            raise RuntimeError(
                f"ICM-20948 not found: WHO_AM_I=0x{chip_id:02X} (expected 0x{_CHIP_ID:02X})"
            )

        # Reset
        self._write(_PWR_MGMT_1, 0x80)
        time.sleep(0.01)
        # Auto-select best clock, exit sleep
        self._write(_PWR_MGMT_1, 0x01)
        # Enable all accel + gyro axes
        self._write(_PWR_MGMT_2, 0x00)

        # Configure gyroscope: 100 Hz, low-pass mode 5, ±250 dps
        self._bank(2)
        rate = int((1125.0 / 100) - 1)
        self._write(_GYRO_SMPLRT_DIV, rate)
        # Low-pass enabled, mode 5, ±250 dps
        value = self._read(_GYRO_CONFIG_1) & 0b10001110
        value |= 0b1  # enable LPF
        value |= (5 & 0x07) << 4  # mode 5
        # scale ±250 already 0b00
        self._write(_GYRO_CONFIG_1, value)

        # Configure accelerometer: 100 Hz, low-pass mode 5, ±4g
        rate = int((1125.0 / 100) - 1)
        self._write(_ACCEL_SMPLRT_DIV_1, (rate >> 8) & 0xFF)
        self._write(_ACCEL_SMPLRT_DIV_2, rate & 0xFF)
        value = self._read(_ACCEL_CONFIG) & 0b10001110
        value |= 0b1  # enable LPF
        value |= (5 & 0x07) << 4  # mode 5
        value |= 0b01 << 1  # ±4g (better resolution for sea state)
        self._write(_ACCEL_CONFIG, value)

        # I2C master setup for magnetometer passthrough
        self._bank(0)
        self._write(_INT_PIN_CFG, 0x30)

        self._bank(3)
        self._write(_I2C_MST_CTRL, 0x4D)
        self._write(_I2C_MST_DELAY_CTRL, 0x01)

        # Verify magnetometer
        self._bank(0)
        mag_id = self._mag_read(_AK09916_WIA)
        if mag_id != _AK09916_CHIP_ID:
            logger.warning(
                "AK09916 magnetometer not found: WIA=0x%02X (expected 0x%02X)",
                mag_id,
                _AK09916_CHIP_ID,
            )
        else:
            # Reset magnetometer
            self._mag_write(_AK09916_CNTL3, 0x01)
            for _ in range(100):
                if self._mag_read(_AK09916_CNTL3) != 0x01:
                    break
                time.sleep(0.001)

        logger.info("ICM-20948 initialised on i2c address 0x%02X", self._addr)

    # --- Data reads ------------------------------------------------------- #

    def read_accel_gyro(self) -> Tuple[float, float, float, float, float, float]:
        """Read accel (m/s²) and gyro (rad/s). Returns (ax, ay, az, gx, gy, gz)."""
        self._bank(0)
        data = self._read_bytes(_ACCEL_XOUT_H, 12)
        ax, ay, az, gx, gy, gz = struct.unpack(">hhhhhh", data)

        # Accelerometer scale: read from config register
        self._bank(2)
        accel_scale = (self._read(_ACCEL_CONFIG) & 0x06) >> 1
        # LSB/g values for ±2g, ±4g, ±8g, ±16g
        accel_lsb_per_g = [16384.0, 8192.0, 4096.0, 2048.0][accel_scale]

        gyro_scale = (self._read(_GYRO_CONFIG_1) & 0x06) >> 1
        # LSB/(deg/s) for ±250, ±500, ±1000, ±2000 dps
        gyro_lsb_per_dps = [131.0, 65.5, 32.8, 16.4][gyro_scale]

        # Convert to SI: m/s² and rad/s
        ax_ms2 = (ax / accel_lsb_per_g) * _GRAVITY
        ay_ms2 = (ay / accel_lsb_per_g) * _GRAVITY
        az_ms2 = (az / accel_lsb_per_g) * _GRAVITY

        gx_rads = math.radians(gx / gyro_lsb_per_dps)
        gy_rads = math.radians(gy / gyro_lsb_per_dps)
        gz_rads = math.radians(gz / gyro_lsb_per_dps)

        return ax_ms2, ay_ms2, az_ms2, gx_rads, gy_rads, gz_rads

    def read_magnetometer(
        self, timeout: float = 0.1
    ) -> Optional[Tuple[float, float, float]]:
        """Read magnetometer (µT). Returns (mx, my, mz) or None on timeout."""
        try:
            self._mag_write(_AK09916_CNTL2, 0x01)  # single measurement
            t0 = time.monotonic()
            while True:
                if self._mag_read(_AK09916_ST1) & 0x01:
                    break
                if time.monotonic() - t0 > timeout:
                    return None
                time.sleep(0.001)

            data = self._mag_read_bytes(_AK09916_HXL, 6)
            x, y, z = struct.unpack("<hhh", data)
            return x * 0.15, y * 0.15, z * 0.15
        except Exception as exc:
            logger.debug("Magnetometer read error: %s", exc)
            return None

    def read_temperature(self) -> float:
        """Read die temperature in °C."""
        self._bank(0)
        data = self._read_bytes(_TEMP_OUT_H, 2)
        raw = struct.unpack(">h", data)[0]
        return ((raw - _TEMP_OFFSET) / _TEMP_SENSITIVITY) + _TEMP_OFFSET


# --------------------------------------------------------------------------- #
# Async wrapper                                                                #
# --------------------------------------------------------------------------- #


class IMUReader:
    """Async wrapper around the ICM-20948 driver.

    Use the ``create()`` class method to instantiate — it returns None
    when the hardware is absent (e.g. running on a Mac).

    When *auto_detect* is True (the default), the factory probes the
    I2C bus for known IMU chips before falling back to the given address.
    """

    def __init__(
        self, driver: _ICM20948Driver, *, chip_name: str = "ICM-20948"
    ) -> None:
        self._driver = driver
        self._chip_name = chip_name
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Gravity unit vector in IMU body frame (set by calibration).
        self._gravity_unit: Optional[Tuple[float, float, float]] = None
        # Running sums for progressive gravity estimation
        self._grav_sum_x: float = 0.0
        self._grav_sum_y: float = 0.0
        self._grav_sum_z: float = 0.0
        self._grav_n: int = 0

    @property
    def chip_name(self) -> str:
        """Name of the detected/configured chip."""
        return self._chip_name

    @classmethod
    async def create(
        cls,
        bus_number: int = 1,
        address: int = _I2C_ADDR,
        auto_detect: bool = True,
    ) -> Optional["IMUReader"]:
        """Try to open the IMU.  Returns None if hardware is unavailable.

        When *auto_detect* is True, discovers all available I2C buses
        and scans each one for known IMU chips before falling back to
        *address* on *bus_number*.  Currently only ICM-20948 has a full
        driver; other detected chips are logged but the reader still
        attempts ICM-20948 init at the detected address.
        """
        detected_chip_name = "ICM-20948"
        effective_address = address
        effective_bus = bus_number

        if auto_detect:
            try:
                from imu_detect import detect_imu

                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, detect_imu)
                if result is not None:
                    detected_chip_name = result.chip.chip_name
                    effective_address = result.address
                    effective_bus = result.bus_number
                    logger.info(
                        "Auto-detected %s at bus=%d addr=0x%02X",
                        detected_chip_name,
                        effective_bus,
                        effective_address,
                    )
                    if detected_chip_name != "ICM-20948":
                        logger.warning(
                            "Detected %s but only ICM-20948 driver is implemented; "
                            "attempting ICM-20948 init at 0x%02X anyway",
                            detected_chip_name,
                            effective_address,
                        )
                else:
                    logger.info(
                        "Auto-detect found no known IMU on any bus; "
                        "falling back to bus=%d addr=0x%02X",
                        bus_number,
                        address,
                    )
            except Exception as exc:
                logger.debug(
                    "Auto-detect failed: %s — falling back to bus=%d 0x%02X",
                    exc,
                    bus_number,
                    address,
                )

        try:
            loop = asyncio.get_running_loop()
            driver = await loop.run_in_executor(
                None, lambda: _ICM20948Driver(effective_bus, effective_address)
            )
            await loop.run_in_executor(None, driver.init)
            reader = cls(driver, chip_name=detected_chip_name)
            reader._loop = loop
            logger.info(
                "IMU reader ready (%s, bus=%d, addr=0x%02X)",
                detected_chip_name,
                effective_bus,
                effective_address,
            )
            return reader
        except Exception as exc:
            logger.info("IMU not available: %s", exc)
            return None

    @property
    def is_calibrated(self) -> bool:
        """True when the gravity direction has been calibrated."""
        return self._gravity_unit is not None

    @property
    def gravity_unit(self) -> Optional[Tuple[float, float, float]]:
        """Gravity unit vector in IMU body frame, or None if uncalibrated."""
        return self._gravity_unit

    async def calibrate(
        self,
        duration_s: float = 2.0,
        rate_hz: float = 50.0,
    ) -> Tuple[float, float, float]:
        """Seed gravity estimate with a short burst of readings.

        Collects *duration_s* seconds of accelerometer readings at
        *rate_hz* and averages them to get an initial gravity estimate.
        This is called once at startup; subsequent readings continue to
        refine the estimate via :meth:`_update_gravity`.

        Over many wave cycles the oscillatory accelerations average to
        zero, so the mean converges to the true gravity vector regardless
        of sea state.  Even a short burst gives a usable direction when
        the IMU is mounted at ~90° — the dominant axis is unmistakable.

        Returns the gravity unit vector ``(gx, gy, gz)``.
        """
        loop = self._loop or asyncio.get_running_loop()
        interval = 1.0 / rate_hz
        n_samples = int(duration_s * rate_hz)

        for _ in range(n_samples):
            try:
                ax, ay, az, _, _, _ = await loop.run_in_executor(
                    None, self._driver.read_accel_gyro
                )
                self._grav_sum_x += ax
                self._grav_sum_y += ay
                self._grav_sum_z += az
                self._grav_n += 1
            except Exception:
                pass
            await asyncio.sleep(interval)

        self._recompute_gravity_unit()
        return self._gravity_unit or (0.0, 0.0, -1.0)

    def _update_gravity(self, ax: float, ay: float, az: float) -> None:
        """Incorporate a new accel reading into the running gravity estimate.

        Called on every IMU read (50 Hz).  Over many wave cycles the
        oscillatory component averages out, progressively refining the
        gravity direction.  Uses exponential weighting with a half-life
        of ~300 s (15 000 samples at 50 Hz) so the estimate tracks slow
        orientation changes (e.g. heel under sail) but remains stable
        against wave-frequency noise.
        """
        # Exponential decay factor: alpha = 1 - exp(-1/(halflife_samples))
        # With halflife = 15000 samples (~5 min at 50 Hz):
        #   alpha ≈ 6.67e-5, so (1-alpha)^15000 ≈ 0.5
        _ALPHA = 6.67e-5

        if self._grav_n == 0:
            # First sample ever — initialise
            self._grav_sum_x = ax
            self._grav_sum_y = ay
            self._grav_sum_z = az
            self._grav_n = 1
        else:
            # Exponential moving average
            self._grav_sum_x = (1.0 - _ALPHA) * self._grav_sum_x + _ALPHA * ax
            self._grav_sum_y = (1.0 - _ALPHA) * self._grav_sum_y + _ALPHA * ay
            self._grav_sum_z = (1.0 - _ALPHA) * self._grav_sum_z + _ALPHA * az

        # Recompute unit vector every 50 samples (~1 Hz) to avoid
        # sqrt on every call
        if self._grav_n % 50 == 0:
            self._recompute_gravity_unit()
        self._grav_n += 1

    def _recompute_gravity_unit(self) -> None:
        """Normalise the running gravity sum into a unit vector."""
        sx, sy, sz = self._grav_sum_x, self._grav_sum_y, self._grav_sum_z
        mag = math.sqrt(sx * sx + sy * sy + sz * sz)
        if mag < 0.1:
            return  # not enough data yet
        gx, gy, gz = sx / mag, sy / mag, sz / mag
        prev = self._gravity_unit
        self._gravity_unit = (gx, gy, gz)

        # Log on first calibration or significant change
        if prev is None:
            tilt_deg = math.degrees(math.acos(min(1.0, max(-1.0, gz))))
            logger.info(
                "IMU gravity calibration: body-frame direction = "
                "(%.3f, %.3f, %.3f), tilt from chip Z = %.1f° "
                "(%d samples)",
                gx,
                gy,
                gz,
                tilt_deg,
                self._grav_n,
            )

    async def read_sample(self) -> IMUSample:
        """Read a complete sample (accel + gyro + mag + temp)."""
        loop = self._loop or asyncio.get_running_loop()
        now = datetime.now(timezone.utc)

        ax, ay, az, gx, gy, gz = await loop.run_in_executor(
            None, self._driver.read_accel_gyro
        )
        # Continuously refine gravity estimate
        self._update_gravity(ax, ay, az)

        mag = await loop.run_in_executor(None, self._driver.read_magnetometer)
        temp = await loop.run_in_executor(None, self._driver.read_temperature)

        return IMUSample(
            timestamp=now,
            accel_x=ax,
            accel_y=ay,
            accel_z=az,
            gyro_x=gx,
            gyro_y=gy,
            gyro_z=gz,
            mag_x=mag[0] if mag else None,
            mag_y=mag[1] if mag else None,
            mag_z=mag[2] if mag else None,
            temperature=temp,
            _gravity_unit=self._gravity_unit,
        )

    async def read_accel_gyro_only(self) -> IMUSample:
        """Fast path: accel + gyro only (skip slow magnetometer)."""
        loop = self._loop or asyncio.get_running_loop()
        now = datetime.now(timezone.utc)

        ax, ay, az, gx, gy, gz = await loop.run_in_executor(
            None, self._driver.read_accel_gyro
        )
        # Continuously refine gravity estimate
        self._update_gravity(ax, ay, az)

        return IMUSample(
            timestamp=now,
            accel_x=ax,
            accel_y=ay,
            accel_z=az,
            gyro_x=gx,
            gyro_y=gy,
            gyro_z=gz,
            _gravity_unit=self._gravity_unit,
        )

    def close(self) -> None:
        """Release the I2C bus."""
        try:
            self._driver.close()
        except Exception:
            pass
