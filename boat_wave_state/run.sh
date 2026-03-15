#!/usr/bin/env bash
set -e

# HA App entry point for boat_wave_state.
# Reads user configuration from /data/options.json and launches main.py.

OPTIONS_FILE="/data/options.json"

# Default values (overridden by options.json if present)
SIGNALK_URL="http://primrose.local:3000"
SAMPLE_RATE_HZ="2.0"
IMU_ENABLED="true"
IMU_AUTO_DETECT="true"
IMU_BUS_NUMBER="1"
IMU_SAMPLE_RATE_HZ="50.0"
IMU_INCLUDE_MAG="true"
PUBLISH_TO_SIGNALK="true"
ENABLE_PLOTS="false"
LOG_LEVEL="info"

# Parse options.json if it exists
if [ -f "$OPTIONS_FILE" ]; then
    echo "[boat_wave_state] Reading config from $OPTIONS_FILE"

    # Use python3 to parse JSON (jq may not be available)
    SIGNALK_URL=$(python3 -c "import json; print(json.load(open('$OPTIONS_FILE')).get('signalk_url', '$SIGNALK_URL'))")
    SAMPLE_RATE_HZ=$(python3 -c "import json; print(json.load(open('$OPTIONS_FILE')).get('sample_rate_hz', $SAMPLE_RATE_HZ))")
    IMU_ENABLED=$(python3 -c "import json; print(str(json.load(open('$OPTIONS_FILE')).get('imu_enabled', True)).lower())")
    IMU_AUTO_DETECT=$(python3 -c "import json; print(str(json.load(open('$OPTIONS_FILE')).get('imu_auto_detect', True)).lower())")
    IMU_BUS_NUMBER=$(python3 -c "import json; print(json.load(open('$OPTIONS_FILE')).get('imu_bus_number', $IMU_BUS_NUMBER))")
    IMU_SAMPLE_RATE_HZ=$(python3 -c "import json; print(json.load(open('$OPTIONS_FILE')).get('imu_sample_rate_hz', $IMU_SAMPLE_RATE_HZ))")
    IMU_INCLUDE_MAG=$(python3 -c "import json; print(str(json.load(open('$OPTIONS_FILE')).get('imu_include_mag', True)).lower())")
    PUBLISH_TO_SIGNALK=$(python3 -c "import json; print(str(json.load(open('$OPTIONS_FILE')).get('publish_to_signalk', True)).lower())")
    ENABLE_PLOTS=$(python3 -c "import json; print(str(json.load(open('$OPTIONS_FILE')).get('enable_plots', False)).lower())")
    LOG_LEVEL=$(python3 -c "import json; print(json.load(open('$OPTIONS_FILE')).get('log_level', '$LOG_LEVEL'))")
else
    echo "[boat_wave_state] No options.json found, using defaults"
fi

echo "[boat_wave_state] Signal K URL:     $SIGNALK_URL"
echo "[boat_wave_state] Sample rate:      $SAMPLE_RATE_HZ Hz"
echo "[boat_wave_state] IMU enabled:      $IMU_ENABLED (auto_detect=$IMU_AUTO_DETECT, bus=$IMU_BUS_NUMBER)"
echo "[boat_wave_state] IMU rate:         $IMU_SAMPLE_RATE_HZ Hz (mag=$IMU_INCLUDE_MAG)"
echo "[boat_wave_state] Publish to SK:    $PUBLISH_TO_SIGNALK"
echo "[boat_wave_state] Log level:        $LOG_LEVEL"

# Export as environment variables for main.py to read
export BOAT_STATE_SIGNALK_URL="$SIGNALK_URL"
export BOAT_STATE_SAMPLE_RATE_HZ="$SAMPLE_RATE_HZ"
export BOAT_STATE_IMU_ENABLED="$IMU_ENABLED"
export BOAT_STATE_IMU_AUTO_DETECT="$IMU_AUTO_DETECT"
export BOAT_STATE_IMU_BUS_NUMBER="$IMU_BUS_NUMBER"
export BOAT_STATE_IMU_SAMPLE_RATE_HZ="$IMU_SAMPLE_RATE_HZ"
export BOAT_STATE_IMU_INCLUDE_MAG="$IMU_INCLUDE_MAG"
export BOAT_STATE_PUBLISH_TO_SIGNALK="$PUBLISH_TO_SIGNALK"
export BOAT_STATE_ENABLE_PLOTS="$ENABLE_PLOTS"
export BOAT_STATE_LOG_LEVEL="$LOG_LEVEL"

# Output goes to /share/boat_wave_state/ so it's accessible from HA
export BOAT_STATE_OUTPUT_DIR="/share/boat_wave_state"
mkdir -p "$BOAT_STATE_OUTPUT_DIR"

# Build CLI args
ARGS="live --url $SIGNALK_URL"
if [ "$ENABLE_PLOTS" = "true" ]; then
    ARGS="$ARGS --plots"
fi

echo "[boat_wave_state] Starting: python3 src/main.py $ARGS"
exec python3 /app/src/main.py $ARGS
