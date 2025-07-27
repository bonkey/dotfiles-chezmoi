#!/usr/bin/env zsh -l

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Switch resolution
# @raycast.mode silent

# Optional parameters:
# @raycast.icon 🖥

# Documentation:
# @raycast.author Daniel Bauke

# Check modes:
# displayplacer list | grep -E '(current mode|^displayplacer)'

source "${HOME}/bin/_common.zsh"

mbp16_dell="49CA87DC-1B8E-41F4-9D42-F698EC113363"
mba13_dell="49A9953F-F205-2C3C-0857-D6964E3302DB"

mba16_asd="0333F8BB-D366-4A2C-91DB-D866EEE73335"
mba13_asd="0333F8BB-D366-4A2C-91DB-D866EEE73335" # TODO: Update ID

internal="37D8832A-2D66-02CA-B9F7-8F30A301B230"

dell_hi_res_mode="175"
dell_low_res_mode="131"

asd_hi_res_mode="13"
asd_low_res_mode="11"

mbp16_int_hi_res_mode="72"
mbp16_int_low_res_mode="30"
mba13_int_hi_res_mode="11"
mba13_int_low_res_mode="6"

mba13_ext=$mba13_asd
mba16_ext=$mba16_asd
ext_hi_res_mode=$asd_hi_res_mode
ext_low_res_mode=$asd_low_res_mode

dp_cmd=/opt/homebrew/bin/displayplacer

is_current_mode() {
    $dp_cmd list | grep -qE "mode ${1}:.*<-- current mode"
    return $?
}

is_display() {
    $dp_cmd list | tail -1 | grep -qE "$1"
    return $?
}

is_mbp16() {
    is_display "id:${internal}[^\"]+hz:120"
    return $?
}

is_mba13() {
    is_display "id:${internal}[^\"]+hz:60"
    return $?
}

ext_display_id() {
    $dp_cmd list | grep -E "^Persistent screen id: (${mba16_ext}|${mba13_ext})" | sd '^Persistent screen id: ' ''
}

is_ext_connected() {
    is_display "id:(${mbp16_ext}|${mba13_ext})"
    return $?
}

new_modes=()

if is_mbp16; then
    origin="0,0"

    int_hi_res_mode=$mbp16_int_hi_res_mode
    int_low_res_mode=$mbp16_int_low_res_mode

    if is_current_mode $int_hi_res_mode; then # high resolution
        new_int_mode=$int_low_res_mode
        if is_ext_connected; then
            new_modes+=("id:$(ext_display_id) mode:$dell_low_res_mode")
            origin="1920,232"
        fi
    else
        new_int_mode=$int_hi_res_mode
        if is_ext_connected; then
            new_modes+=("id:$(ext_display_id) mode:$dell_hi_res_mode")
            origin="3360,0"
        fi
    fi
    new_modes+=("id:${internal} mode:${new_int_mode} origin:(${origin})")
elif is_mba13; then
    origin="0,0"
    
    int_hi_res_mode=$mba13_int_hi_res_mode
    int_low_res_mode=$mba13_int_low_res_mode

    if is_current_mode $int_hi_res_mode; then # high resolution
        new_int_mode="$int_low_res_mode"
        if is_ext_connected; then
            new_modes+=("id:$(ext_display_id) mode:$ext_low_res_mode")
            origin="1920,280"
        fi
    else
        new_int_mode=$int_hi_res_mode
        if is_ext_connected; then
            new_modes+=("id:$(ext_display_id) mode:$ext_hi_res_mode")
            origin="2560,120"
        fi
    fi
    new_modes+=("id:${internal} mode:${new_int_mode} origin:(${origin})")
else
    echo "No internal displays available. Quitting"
    exit 1
fi

$dp_cmd ${new_modes[@]}

$dp_cmd list | grep '<-- current mode' | sd '(.*)<-- current mode.*' '$1'
