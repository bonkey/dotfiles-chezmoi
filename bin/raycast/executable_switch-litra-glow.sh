#!/usr/bin/env zsh

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Switch Litra Glow
# @raycast.mode silent

# Optional parameters:
# @raycast.icon 💡
# @raycast.argument1 { "type": "text", "placeholder": "turn on", "optional": true}


# Documentation:
# @raycast.author Daniel Bauke

hid_litra_cmd() {
    "${HOME}"/bin/hidapitester --vidpid 046d/c900 --open --length 20 "$@" &>/dev/null
}

litra_send_output() {
    hid_litra_cmd --send-output "$@"
}

litra_on() {
    echo "🕶 Turning Lamp on..."
    litra_send_output '0x11,0xff,0x04,0x1c,0x01'
}

litra_off() {
    echo "👓 Turning Lamp off.."
    litra_send_output '0x11,0xff,0x04,0x1c'
}

if [[ -z "$1" ]]; then
    litra_off
else
    litra_on
fi