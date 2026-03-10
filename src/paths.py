"""Canonical Signal K paths for vessel self data only.

Internal units follow Signal K conventions:
  Angles      – radians
  Speeds      – m/s
  Rate-of-turn – rad/s
  Position    – degrees (latitude / longitude)
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
COURSE_OVER_GROUND_TRUE = "navigation.courseOverGroundTrue"  # rad
HEADING_TRUE = "navigation.headingTrue"                    # rad
HEADING_MAGNETIC = "navigation.headingMagnetic"            # rad

# --------------------------------------------------------------------------- #
# Wind (on self)                                                               #
# --------------------------------------------------------------------------- #
WIND_SPEED_TRUE = "environment.wind.speedTrue"             # m/s
WIND_ANGLE_TRUE_WATER = "environment.wind.angleTrueWater"  # rad
WIND_SPEED_APPARENT = "environment.wind.speedApparent"     # m/s
WIND_ANGLE_APPARENT = "environment.wind.angleApparent"     # rad

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
    COURSE_OVER_GROUND_TRUE,
    HEADING_TRUE,
    WIND_SPEED_TRUE,
    WIND_ANGLE_TRUE_WATER,
    WIND_SPEED_APPARENT,
    WIND_ANGLE_APPARENT,
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
    COURSE_OVER_GROUND_TRUE: "cog",
    HEADING_TRUE:            "heading",
    HEADING_MAGNETIC:        "heading_magnetic",
    WIND_SPEED_TRUE:         "wind_speed_true",
    WIND_ANGLE_TRUE_WATER:   "wind_angle_true",
    WIND_SPEED_APPARENT:     "wind_speed_apparent",
    WIND_ANGLE_APPARENT:     "wind_angle_apparent",
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
    COURSE_OVER_GROUND_TRUE: "rad",
    HEADING_TRUE:            "rad",
    HEADING_MAGNETIC:        "rad",
    WIND_SPEED_TRUE:         "m/s",
    WIND_ANGLE_TRUE_WATER:   "rad",
    WIND_SPEED_APPARENT:     "m/s",
    WIND_ANGLE_APPARENT:     "rad",
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
    WIND_ANGLE_APPARENT,
}
