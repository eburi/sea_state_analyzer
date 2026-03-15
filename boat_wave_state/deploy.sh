#!/usr/bin/env bash
set -e

# Deploy boat_wave_state HA App to a Home Assistant device.
#
# Usage:
#   ./deploy.sh [user@host]
#
# Default target: root@192.168.46.222 (Primrose HA device)
#
# This script:
# 1. Assembles a self-contained addon directory in /tmp/boat_wave_state_addon/
# 2. Copies it to /addons/boat_wave_state/ on the HA device via scp
# 3. Prints instructions for installing/rebuilding in HA

TARGET="${1:-root@192.168.46.222}"
ADDON_NAME="boat_wave_state"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="/tmp/${ADDON_NAME}_addon"

echo "=== Deploying $ADDON_NAME to $TARGET ==="
echo "Project dir: $PROJECT_DIR"
echo ""

# 1. Assemble the addon directory
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Copy HA addon files
cp "$SCRIPT_DIR/config.yaml" "$BUILD_DIR/"
cp "$SCRIPT_DIR/Dockerfile" "$BUILD_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$BUILD_DIR/"
cp "$SCRIPT_DIR/run.sh" "$BUILD_DIR/"

# Copy source code
cp -r "$PROJECT_DIR/src" "$BUILD_DIR/src"

echo "Assembled addon in $BUILD_DIR:"
ls -la "$BUILD_DIR/"
echo ""
echo "Source files:"
ls -la "$BUILD_DIR/src/"
echo ""

# 2. Copy to HA device
echo "Copying to $TARGET:/addons/$ADDON_NAME/ ..."
ssh "$TARGET" "mkdir -p /addons/$ADDON_NAME"
scp -r "$BUILD_DIR/"* "$TARGET:/addons/$ADDON_NAME/"

echo ""
echo "=== Deploy complete ==="
echo ""
echo "Next steps on Home Assistant:"
echo "  1. Go to Settings → Apps → App Store"
echo "  2. Click ⋮ (top right) → Check for updates / Reload"
echo "  3. Find 'Boat Wave State' in the Local apps section"
echo "  4. Click Install (first time) or Rebuild (update)"
echo "  5. Configure Signal K URL and IMU settings"
echo "  6. Start the app and check logs"
echo ""
echo "Or via CLI on the HA device:"
echo "  ha store reload && ha apps install local_$ADDON_NAME   # first time"
echo "  ha apps rebuild local_$ADDON_NAME                      # update"
echo "  ha apps start local_$ADDON_NAME"
echo "  ha apps logs local_$ADDON_NAME"
