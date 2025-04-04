#!/usr/bin/env zsh

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Restart Elgato
# @raycast.mode silent

# Optional parameters:
# @raycast.icon ⌨️

# Documentation:
# @raycast.author Daniel Bauke

source "${HOME}/bin/_common.zsh"

killall "Stream Deck"

device_ids=($(uhubctl|grep "0fd9:" | grep -o '\[.*\]' | grep -o '0fd9:[0-9a-f]\+'))

if [ ${#device_ids[@]} -eq 0 ]; then
    echo "❌ No Elgato devices found"
else
    for device_id in "${device_ids[@]}"; do
        echo "Searching for Elgato device at ${device_id}..."
        SD_HUB=$(uhubctl --exact --nodesc --search "$device_id" | head -2  | grep "Current status for hub" | sed -E 's/Current status for hub ([0-9.-]+).*/\1/g')
        SD_PORT=$(uhubctl --exact --nodesc --search "$device_id" | head -2 | grep -A 1 "Current status for hub" | grep "Port" | sed -E 's/.*Port ([0-9]+).*/\1/g')

        if [ -n "$SD_HUB" ] && [ -n "$SD_PORT" ]; then
            echo "✅ Found a device on hub $SD_HUB port $SD_PORT. Restarting..."
            _exec "uhubctl --exact --nodesc --action cycle --repeat 2 --wait 100 --delay 3 --location $SD_HUB --port $SD_PORT"
            sleep 1
        else
            echo "❌ Device ${device_id} not found"
        fi
    done
fi

open -a "Elgato Stream Deck"
