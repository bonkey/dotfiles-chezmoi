#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Mount SSD
# @raycast.mode compact

# Optional parameters:
# @raycast.icon 💾

# Documentation:
# @raycast.author Daniel Bauke

VOLUME_UUID="8C80E631-EB3A-4760-A542-53580C42FF62"
VOLUME_NAME="Daniel SSD"

# Check if already mounted
if mount | grep -q "${VOLUME_UUID}"; then
    echo "SSD already mounted"
    exit 0
fi

# Also check by volume name in /Volumes
if [ -d "/Volumes/${VOLUME_NAME}" ]; then
    echo "SSD already mounted"
    exit 0
fi

# Check if 1Password CLI is signed in
if ! op account get &>/dev/null; then
    echo "1Password CLI not signed in"
    exit 1
fi

# Get password from 1Password
PASSWORD=$(op read "op://nt6ulfcinsq7lcobqjhb2cdx5i/rrslbmjqlnhfha5ippcr6n6kqi/password")

if [ -z "$PASSWORD" ]; then
    echo "Failed to get password from 1Password"
    exit 1
fi

# Unlock and mount the volume
echo "$PASSWORD" | diskutil apfs unlockVolume "$VOLUME_UUID" -stdinpassphrase
