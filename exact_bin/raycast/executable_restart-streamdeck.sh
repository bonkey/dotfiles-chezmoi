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
sleep 5
open -a "Elgato Stream Deck"
