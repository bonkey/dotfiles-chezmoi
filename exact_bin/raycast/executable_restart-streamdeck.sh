#!/usr/bin/env zsh

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Restart Stream Deck
# @raycast.mode silent

# Optional parameters:
# @raycast.icon ⌨️

# Documentation:
# @raycast.author Daniel Bauke

killall "Stream Deck"

for deck_id in '0fd9:0084' '0fd9:0080' ; do
    echo "Searching for Stream Deck at ${deck_id}..."
    SD_HUB=$(uhubctl --search "$deck_id" | head -2  | grep "Current status for hub" | sed -E 's/Current status for hub ([0-9.-]+).*/\1/g')
    SD_PORT=$(uhubctl --search "$deck_id" | head -2 | grep -A 1 "Current status for hub" | grep "Port" | sed -E 's/.*Port ([0-9]+).*/\1/g')

    if [ -n "$SD_HUB" ] && [ -n "$SD_PORT" ]; then
        echo "✅ Found Stream Deck on hub $SD_HUB port $SD_PORT. Restarting..."
        uhubctl -a cycle -d 2 -l $SD_HUB -p $SD_PORT
    else
        echo "❌ Stream Deck not found"
    fi
done

sleep 5
open -a "Elgato Stream Deck"
