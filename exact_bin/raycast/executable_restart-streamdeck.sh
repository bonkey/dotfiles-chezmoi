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
uhubctl -a cycle -d 2 -l 0-2.4.1 -p 2
uhubctl -a cycle -d 2 -l 0-1.1.2 -p 1
sleep 5
open -a "Elgato Stream Deck"
