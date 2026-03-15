"""Canonical Signal K paths for vessel self data only.

Internal units follow Signal K conventions:
  Angles      – radians
  Speeds      – m/s
  Rate-of-turn – rad/s
  Position    – degrees (latitude / longitude)
  Depth       – metres
  Temperature – Kelvin
  Time        – ISO-8601 / UTC datetime

No wave-sensor paths are listed here.  If environment.wave.* arrives from
the server it may be logged in inspect mode, but this project does not depend
on it.
"""
from __future__ import annotations

from typing import Dict, List

# --------------------------------------------------------------------------- #
# Attitude                                                                     #
# --------------------------------------------------------------------------- #
ATTITUDE = "navigation.attitude"          # compound object {roll, pitch, yaw}
ATTITUDE_ROLL = "navigation.attitude.roll"    # rad
ATTITUDE_PITCH = "navigation.attitude.pitch"  # rad
ATTITUDE_YAW = "navigation.attitude.yaw"      # rad
RATE_OF_TURN = "navigation.rateOfTurn"        # rad/s

# --------------------------------------------------------------------------- #
# Vessel movement                                                              #
# --------------------------------------------------------------------------- #
SPEED_OVER_GROUND = "navigation.speedOverGround"           # m/s
SPEED_THROUGH_WATER = "navigation.speedThroughWater"       # m/s
COURSE_OVER_GROUND_TRUE = "navigation.courseOverGroundTrue"  # rad
HEADING_TRUE = "navigation.headingTrue"                    # rad
HEADING_MAGNETIC = "navigation.headingMagnetic"            # rad

# --------------------------------------------------------------------------- #
# Wind (on self)                                                               #
# --------------------------------------------------------------------------- #
WIND_SPEED_TRUE = "environment.wind.speedTrue"             # m/s
WIND_ANGLE_TRUE_WATER = "environment.wind.angleTrueWater"  # rad
WIND_DIRECTION_TRUE = "environment.wind.directionTrue"     # rad (relative to true north)
WIND_SPEED_APPARENT = "environment.wind.speedApparent"     # m/s
WIND_ANGLE_APPARENT = "environment.wind.angleApparent"     # rad

# --------------------------------------------------------------------------- #
# Current                                                                      #
# --------------------------------------------------------------------------- #
CURRENT_DRIFT = "environment.current.drift"                # m/s
CURRENT_SET_TRUE = "environment.current.setTrue"           # rad (direction toward)

# --------------------------------------------------------------------------- #
# Steering / autopilot                                                         #
# --------------------------------------------------------------------------- #
RUDDER_ANGLE = "steering.rudderAngle"                      # rad
AUTOPILOT_STATE = "steering.autopilot.state"               # string (wind/route/standby)

# --------------------------------------------------------------------------- #
# Depth                                                                        #
# --------------------------------------------------------------------------- #
DEPTH_BELOW_TRANSDUCER = "environment.depth.belowTransducer"  # metres

# --------------------------------------------------------------------------- #
# Position / time                                                              #
# --------------------------------------------------------------------------- #
POSITION = "navigation.position"   # {latitude: deg, longitude: deg}
DATETIME = "navigation.datetime"   # ISO-8601 string

# --------------------------------------------------------------------------- #
# Composite path: parent attitude object                                       #
# --------------------------------------------------------------------------- #
ATTITUDE_SUBKEYS = ("roll", "pitch", "yaw")

# --------------------------------------------------------------------------- #
# Subscription list for normal live mode                                      #
# --------------------------------------------------------------------------- #
SUBSCRIPTION_PATHS: List[str] = [
    ATTITUDE,
    ATTITUDE_ROLL,
    ATTITUDE_PITCH,
    ATTITUDE_YAW,
    RATE_OF_TURN,
    SPEED_OVER_GROUND,
    SPEED_THROUGH_WATER,
    COURSE_OVER_GROUND_TRUE,
    HEADING_TRUE,
    WIND_SPEED_TRUE,
    WIND_ANGLE_TRUE_WATER,
    WIND_DIRECTION_TRUE,
    WIND_SPEED_APPARENT,
    WIND_ANGLE_APPARENT,
    CURRENT_DRIFT,
    CURRENT_SET_TRUE,
    RUDDER_ANGLE,
    AUTOPILOT_STATE,
    DEPTH_BELOW_TRANSDUCER,
    POSITION,
    DATETIME,
]

# --------------------------------------------------------------------------- #
# Mapping: SK path -> short field name used in InstantSample                  #
# --------------------------------------------------------------------------- #
PATH_TO_FIELD: Dict[str, str] = {
    ATTITUDE_ROLL:           "roll",
    ATTITUDE_PITCH:          "pitch",
    ATTITUDE_YAW:            "yaw",
    RATE_OF_TURN:            "rate_of_turn",
    SPEED_OVER_GROUND:       "sog",
    SPEED_THROUGH_WATER:     "stw",
    COURSE_OVER_GROUND_TRUE: "cog",
    HEADING_TRUE:            "heading",
    HEADING_MAGNETIC:        "heading_magnetic",
    WIND_SPEED_TRUE:         "wind_speed_true",
    WIND_ANGLE_TRUE_WATER:   "wind_angle_true",
    WIND_DIRECTION_TRUE:     "wind_direction_true",
    WIND_SPEED_APPARENT:     "wind_speed_apparent",
    WIND_ANGLE_APPARENT:     "wind_angle_apparent",
    CURRENT_DRIFT:           "current_drift",
    CURRENT_SET_TRUE:        "current_set",
    RUDDER_ANGLE:            "rudder_angle",
    AUTOPILOT_STATE:         "autopilot_state",
    DEPTH_BELOW_TRANSDUCER:  "depth",
    POSITION:                "position",
    DATETIME:                "nav_datetime",
}

# --------------------------------------------------------------------------- #
# Documented units (Signal K standard)                                        #
# --------------------------------------------------------------------------- #
PATH_UNITS: Dict[str, str] = {
    ATTITUDE_ROLL:           "rad",
    ATTITUDE_PITCH:          "rad",
    ATTITUDE_YAW:            "rad",
    RATE_OF_TURN:            "rad/s",
    SPEED_OVER_GROUND:       "m/s",
    SPEED_THROUGH_WATER:     "m/s",
    COURSE_OVER_GROUND_TRUE: "rad",
    HEADING_TRUE:            "rad",
    HEADING_MAGNETIC:        "rad",
    WIND_SPEED_TRUE:         "m/s",
    WIND_ANGLE_TRUE_WATER:   "rad",
    WIND_DIRECTION_TRUE:     "rad",
    WIND_SPEED_APPARENT:     "m/s",
    WIND_ANGLE_APPARENT:     "rad",
    CURRENT_DRIFT:           "m/s",
    CURRENT_SET_TRUE:        "rad",
    RUDDER_ANGLE:            "rad",
    AUTOPILOT_STATE:         "string",
    DEPTH_BELOW_TRANSDUCER:  "m",
    POSITION:                "degrees",
    DATETIME:                "ISO8601/UTC",
}

# --------------------------------------------------------------------------- #
# Angle paths – used for unwrapping before differentiation                    #
# --------------------------------------------------------------------------- #
ANGLE_PATHS = {
    ATTITUDE_ROLL,
    ATTITUDE_PITCH,
    ATTITUDE_YAW,
    COURSE_OVER_GROUND_TRUE,
    HEADING_TRUE,
    HEADING_MAGNETIC,
    WIND_ANGLE_TRUE_WATER,
    WIND_DIRECTION_TRUE,
    WIND_ANGLE_APPARENT,
    CURRENT_SET_TRUE,
    RUDDER_ANGLE,
}

# --------------------------------------------------------------------------- #
# Wave estimate publish paths (outgoing — written by this app)                #
# --------------------------------------------------------------------------- #
# These are custom paths published back to Signal K.  They are not part of
# the Signal K v1.5 spec but are accepted by signalk-server-node as custom
# data.  environment.heave IS in the spec.
#
# All values follow SI / Signal K conventions:
#   Heights  – metres
#   Periods  – seconds
#   Angles   – radians  (directionTrue is compass bearing of wave travel)
#   Severity – dimensionless 0–1

WAVE_SIGNIFICANT_HEIGHT = "environment.water.waves.significantHeight"  # metres
WAVE_PERIOD = "environment.water.waves.period"                        # seconds
WAVE_DIRECTION_TRUE = "environment.water.waves.directionTrue"         # radians
HEAVE = "environment.heave"                                           # metres (in SK spec)

# Additional detail paths
WAVE_ENCOUNTER_PERIOD = "environment.water.waves.encounterPeriod"     # seconds
WAVE_TRUE_PERIOD = "environment.water.waves.truePeriod"               # seconds (Doppler-corrected)
WAVE_TRUE_WAVELENGTH = "environment.water.waves.trueWavelength"       # metres
WAVE_MOTION_SEVERITY = "environment.water.waves.motionSeverity"       # 0–1
WAVE_MOTION_REGIME = "environment.water.waves.motionRegime"           # calm/moderate/active/heavy
WAVE_ENCOUNTER_DIRECTION = "environment.water.waves.encounterDirection"  # beam/head/following/quartering
WAVE_COMFORT_PROXY = "environment.water.waves.comfortProxy"           # 0–1
WAVE_PERIOD_CONFIDENCE = "environment.water.waves.periodConfidence"    # 0–1

# Spectral partition paths — wind-wave + two swell components
# These follow the same naming convention as Open-Meteo / Copernicus
# forecast partition data for easy comparison.
WAVE_WIND_WAVE_HEIGHT = "environment.water.waves.windWave.height"          # metres
WAVE_WIND_WAVE_PERIOD = "environment.water.waves.windWave.period"          # seconds
WAVE_WIND_WAVE_CONFIDENCE = "environment.water.waves.windWave.confidence"  # 0–1
WAVE_SWELL_1_HEIGHT = "environment.water.waves.swell1.height"              # metres
WAVE_SWELL_1_PERIOD = "environment.water.waves.swell1.period"              # seconds
WAVE_SWELL_1_CONFIDENCE = "environment.water.waves.swell1.confidence"      # 0–1
WAVE_SWELL_2_HEIGHT = "environment.water.waves.swell2.height"              # metres
WAVE_SWELL_2_PERIOD = "environment.water.waves.swell2.period"              # seconds
WAVE_SWELL_2_CONFIDENCE = "environment.water.waves.swell2.confidence"      # 0–1

# All publish paths for iteration
PUBLISH_PATHS: List[str] = [
    WAVE_SIGNIFICANT_HEIGHT,
    WAVE_PERIOD,
    WAVE_DIRECTION_TRUE,
    HEAVE,
    WAVE_ENCOUNTER_PERIOD,
    WAVE_TRUE_PERIOD,
    WAVE_TRUE_WAVELENGTH,
    WAVE_MOTION_SEVERITY,
    WAVE_MOTION_REGIME,
    WAVE_ENCOUNTER_DIRECTION,
    WAVE_COMFORT_PROXY,
    WAVE_PERIOD_CONFIDENCE,
    WAVE_WIND_WAVE_HEIGHT,
    WAVE_WIND_WAVE_PERIOD,
    WAVE_WIND_WAVE_CONFIDENCE,
    WAVE_SWELL_1_HEIGHT,
    WAVE_SWELL_1_PERIOD,
    WAVE_SWELL_1_CONFIDENCE,
    WAVE_SWELL_2_HEIGHT,
    WAVE_SWELL_2_PERIOD,
    WAVE_SWELL_2_CONFIDENCE,
]

# --------------------------------------------------------------------------- #
# Wave path metadata (units, descriptions, display names)                     #
# --------------------------------------------------------------------------- #
# Sent as a Signal K meta delta on startup so gauges and dashboards can
# show proper units and labels.  Keys match the publish paths above.

WAVE_PATH_META: Dict[str, Dict[str, object]] = {
    WAVE_SIGNIFICANT_HEIGHT: {
        "units": "m",
        "description": "Estimated significant wave height (Hs) from vessel motion",
        "displayName": "Wave Height (Hs)",
        "shortName": "Hs",
    },
    WAVE_PERIOD: {
        "units": "s",
        "description": "Dominant wave period as encountered by the vessel",
        "displayName": "Wave Period",
        "shortName": "T",
    },
    WAVE_DIRECTION_TRUE: {
        "units": "rad",
        "description": "True direction waves are coming from, relative to true north",
        "displayName": "Wave Direction",
        "shortName": "Dir",
    },
    HEAVE: {
        "units": "m",
        "description": "Vertical displacement (heave) from Kalman-filtered accelerometer",
        "displayName": "Heave",
        "shortName": "Heave",
    },
    WAVE_ENCOUNTER_PERIOD: {
        "units": "s",
        "description": "Wave encounter period as observed by the vessel (not Doppler-corrected)",
        "displayName": "Encounter Period",
        "shortName": "Te",
    },
    WAVE_TRUE_PERIOD: {
        "units": "s",
        "description": "True wave period after Doppler correction for vessel speed",
        "displayName": "True Period",
        "shortName": "Tt",
    },
    WAVE_TRUE_WAVELENGTH: {
        "units": "m",
        "description": "True wavelength after Doppler correction (deep-water dispersion)",
        "displayName": "Wavelength",
        "shortName": "λ",
    },
    WAVE_MOTION_SEVERITY: {
        "units": "ratio",
        "description": "Composite motion severity index (0 = calm, 1 = extreme)",
        "displayName": "Motion Severity",
        "shortName": "Sev",
        "displayScale": {"lower": 0, "upper": 1, "type": "linear"},
    },
    WAVE_MOTION_REGIME: {
        "description": "Motion regime classification",
        "displayName": "Motion Regime",
        "shortName": "Regime",
        "enum": ["calm", "moderate", "active", "heavy"],
    },
    WAVE_ENCOUNTER_DIRECTION: {
        "description": "Wave encounter direction relative to vessel heading",
        "displayName": "Encounter Direction",
        "shortName": "Dir",
        "enum": [
            "head_or_following_like",
            "beam_like",
            "quartering_like",
            "confused_like",
            "mixed",
        ],
    },
    WAVE_COMFORT_PROXY: {
        "units": "ratio",
        "description": "Comfort proxy combining motion severity and regularity (0 = comfortable, 1 = uncomfortable)",
        "displayName": "Comfort",
        "shortName": "Cmft",
        "displayScale": {"lower": 0, "upper": 1, "type": "linear"},
    },
    WAVE_PERIOD_CONFIDENCE: {
        "units": "ratio",
        "description": "Confidence in dominant period estimate (0 = low, 1 = high)",
        "displayName": "Period Confidence",
        "shortName": "Tconf",
        "displayScale": {"lower": 0, "upper": 1, "type": "linear"},
    },
    # Spectral partitions — wind-wave
    WAVE_WIND_WAVE_HEIGHT: {
        "units": "m",
        "description": "Significant height of wind-wave component (highest-frequency partition)",
        "displayName": "Wind Wave Height",
        "shortName": "Hs_ww",
    },
    WAVE_WIND_WAVE_PERIOD: {
        "units": "s",
        "description": "Peak period of wind-wave component",
        "displayName": "Wind Wave Period",
        "shortName": "T_ww",
    },
    WAVE_WIND_WAVE_CONFIDENCE: {
        "units": "ratio",
        "description": "Confidence in wind-wave partition (energy share × peak sharpness)",
        "displayName": "Wind Wave Confidence",
        "shortName": "C_ww",
        "displayScale": {"lower": 0, "upper": 1, "type": "linear"},
    },
    # Spectral partitions — primary swell
    WAVE_SWELL_1_HEIGHT: {
        "units": "m",
        "description": "Significant height of primary swell component",
        "displayName": "Swell 1 Height",
        "shortName": "Hs_s1",
    },
    WAVE_SWELL_1_PERIOD: {
        "units": "s",
        "description": "Peak period of primary swell component",
        "displayName": "Swell 1 Period",
        "shortName": "T_s1",
    },
    WAVE_SWELL_1_CONFIDENCE: {
        "units": "ratio",
        "description": "Confidence in primary swell partition",
        "displayName": "Swell 1 Confidence",
        "shortName": "C_s1",
        "displayScale": {"lower": 0, "upper": 1, "type": "linear"},
    },
    # Spectral partitions — secondary swell
    WAVE_SWELL_2_HEIGHT: {
        "units": "m",
        "description": "Significant height of secondary swell component (lowest-frequency partition)",
        "displayName": "Swell 2 Height",
        "shortName": "Hs_s2",
    },
    WAVE_SWELL_2_PERIOD: {
        "units": "s",
        "description": "Peak period of secondary swell component",
        "displayName": "Swell 2 Period",
        "shortName": "T_s2",
    },
    WAVE_SWELL_2_CONFIDENCE: {
        "units": "ratio",
        "description": "Confidence in secondary swell partition",
        "displayName": "Swell 2 Confidence",
        "shortName": "C_s2",
        "displayScale": {"lower": 0, "upper": 1, "type": "linear"},
    },
}
