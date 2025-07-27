#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Restart ethernet
# @raycast.mode compact

# Optional parameters:
# @raycast.icon 🔌

# Documentation:
# @raycast.author Daniel Bauke

macs=("bc:6a:2f:4b:6e:39" "f4:d4:88:5c:ed:82")

sudo /Applications/VMware\ Carbon\ Black\ Cloud/VMware\ CBCloud.app/Contents/MacOS/VMware\ CBCloud -nd

for mac in ${macs[@]}; do
    iface=$(ifconfig | jc -p --ifconfig | jq -r '.[] | select(.mac_addr == "'${mac}'") | .name')
    echo "Restarting '$iface' ($mac)..."

    sudo ifconfig $iface down
    sudo ifconfig $iface up
done

sleep 3

sudo /Applications/VMware\ Carbon\ Black\ Cloud/VMware\ CBCloud.app/Contents/MacOS/VMware\ CBCloud -ne
