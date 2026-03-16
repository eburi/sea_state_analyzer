#!/usr/bin/with-contenv bashio
set -e

# HA Add-on entry point for sea_state_analyzer.
# Reads user configuration via bashio and launches main.py.

bashio::log.info "Reading add-on configuration..."

# Read config values via bashio (falls back to defaults from config.yaml)
SIGNALK_URL="$(bashio::config 'signalk_url')"
SAMPLE_RATE_HZ="$(bashio::config 'sample_rate_hz')"
IMU_ENABLED="$(bashio::config 'imu_enabled')"
IMU_AUTO_DETECT="$(bashio::config 'imu_auto_detect')"
IMU_BUS_NUMBER="$(bashio::config 'imu_bus_number')"
IMU_SAMPLE_RATE_HZ="$(bashio::config 'imu_sample_rate_hz')"
IMU_INCLUDE_MAG="$(bashio::config 'imu_include_mag')"
PUBLISH_TO_SIGNALK="$(bashio::config 'publish_to_signalk')"
ENABLE_PLOTS="$(bashio::config 'enable_plots')"
LOG_LEVEL="$(bashio::config 'log_level')"

bashio::log.info "Signal K URL:     ${SIGNALK_URL}"
bashio::log.info "Sample rate:      ${SAMPLE_RATE_HZ} Hz"
bashio::log.info "IMU enabled:      ${IMU_ENABLED} (auto_detect=${IMU_AUTO_DETECT}, bus=${IMU_BUS_NUMBER})"
bashio::log.info "IMU rate:         ${IMU_SAMPLE_RATE_HZ} Hz (mag=${IMU_INCLUDE_MAG})"
bashio::log.info "Publish to SK:    ${PUBLISH_TO_SIGNALK}"
bashio::log.info "Log level:        ${LOG_LEVEL}"

# Export as environment variables for main.py to read via Config.from_env()
export SEA_STATE_SIGNALK_URL="${SIGNALK_URL}"
export SEA_STATE_SAMPLE_RATE_HZ="${SAMPLE_RATE_HZ}"
export SEA_STATE_IMU_ENABLED="${IMU_ENABLED}"
export SEA_STATE_IMU_AUTO_DETECT="${IMU_AUTO_DETECT}"
export SEA_STATE_IMU_BUS_NUMBER="${IMU_BUS_NUMBER}"
export SEA_STATE_IMU_SAMPLE_RATE_HZ="${IMU_SAMPLE_RATE_HZ}"
export SEA_STATE_IMU_INCLUDE_MAG="${IMU_INCLUDE_MAG}"
export SEA_STATE_PUBLISH_TO_SIGNALK="${PUBLISH_TO_SIGNALK}"
export SEA_STATE_ENABLE_PLOTS="${ENABLE_PLOTS}"
export SEA_STATE_LOG_LEVEL="${LOG_LEVEL}"

# Override data paths for HA (defaults are ~/.sea_state_analyzer/ for bare OS)
export SEA_STATE_AUTH_TOKEN_FILE="/data/signalk_token.json"
export SEA_STATE_LEARNER_PERSIST_PATH="/data/vessel_rao.json"

# Output goes to /share/sea_state_analyzer/ so it's accessible from HA
export SEA_STATE_OUTPUT_DIR="/share/sea_state_analyzer"
mkdir -p "${SEA_STATE_OUTPUT_DIR}"

# Build CLI args
ARGS="live --url ${SIGNALK_URL}"
if bashio::var.true "${ENABLE_PLOTS}"; then
    ARGS="${ARGS} --plots"
fi

bashio::log.info "Starting: python3 src/main.py ${ARGS}"
exec python3 /app/src/main.py ${ARGS}
