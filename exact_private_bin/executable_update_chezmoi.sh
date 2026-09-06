#!/usr/bin/env zsh -l

# Runs the update inside its own Herdr workspace, so it keeps running when the
# terminal window goes away. Called without WORKER_ENV the script only creates
# that workspace and starts itself again inside it.
readonly SCRIPT_PATH=${0:A}
readonly WORKER_ENV='UPDATE_CHEZMOI_WORKER'
readonly WORKSPACE_LABEL='chezmoi update'
readonly BANNER='chezmoi update starts'

ensure_herdr_server() {
    herdr workspace list &>/dev/null && return 0
    herdr server &>/dev/null &!
    for _ in {1..20}; do
        sleep 0.5
        herdr workspace list &>/dev/null && return 0
    done
    return 1
}

# Prints the ID of the workspace labelled WORKSPACE_LABEL, if one exists.
find_workspace() {
    herdr workspace list | jq -r --arg label "$WORKSPACE_LABEL" \
        '[.result.workspaces[] | select(.label == $label) | .workspace_id] | first // empty'
}

# A pane is busy when something other than its own shell owns the foreground.
# An unreadable pane counts as busy so the update never types into it blindly.
pane_is_busy() {
    local info
    info=$(herdr pane process-info --pane "$1" 2>/dev/null) || return 0
    print -r -- "$info" \
        | jq -e '.result.process_info | .foreground_process_group_id != .shell_pid' &>/dev/null
}

# Prints the first pane of the workspace, but only when every pane is idle.
# A second argument names a pane to leave out of the check.
idle_pane_in_workspace() {
    local workspace=$1 ignored=${2:-}
    local -a panes
    panes=(${(f)"$(herdr pane list --workspace "$workspace" | jq -r '.result.panes[].pane_id')"})
    (( $#panes )) || return 1
    local pane
    for pane in $panes; do
        [[ $pane == $ignored ]] && continue
        pane_is_busy "$pane" && return 1
    done
    print -r -- "$panes[1]"
}

# Prints "<workspace_id> <pane_id>" of the pane this script runs in, if any.
caller_location() {
    [[ ${HERDR_ENV:-} == 1 ]] || return 1
    herdr pane current --current 2>/dev/null \
        | jq -er '.result.pane | "\(.workspace_id) \(.pane_id)"'
}

skip_busy() {
    print "Herdr workspace '$WORKSPACE_LABEL' ($1) is busy. Skipping."
}

launch_in_herdr() {
    if ! command -v herdr &>/dev/null; then
        print -u2 'herdr is not installed.'
        return 1
    fi

    if ! ensure_herdr_server; then
        print -u2 'Cannot reach a Herdr server.'
        return 1
    fi

    local workspace pane caller_workspace caller_pane
    workspace=$(find_workspace)
    read -r caller_workspace caller_pane <<< "$(caller_location)"

    if [[ -n $workspace && $workspace == $caller_workspace ]]; then
        # This shell already sits in the workspace and is busy with this very
        # script, so leave it out of the check and run the update right here.
        if ! idle_pane_in_workspace "$workspace" "$caller_pane" >/dev/null; then
            skip_busy "$workspace"
            return 0
        fi
        run_update
        return
    fi

    if [[ -n $workspace ]]; then
        if ! pane=$(idle_pane_in_workspace "$workspace"); then
            skip_busy "$workspace"
            return 0
        fi
        herdr workspace focus "$workspace" &>/dev/null
    else
        local created
        created=$(herdr workspace create --label "$WORKSPACE_LABEL" --cwd "$HOME" --focus) || return 1
        pane=$(print -r -- "$created" | jq -r '.result.root_pane.pane_id')
        # A fresh pane shell needs a moment before it reads typed input.
        sleep 1
    fi

    herdr pane run "$pane" "$WORKER_ENV=1 ${(q-)SCRIPT_PATH}" || return 1

    # The worker prints BANNER first, which confirms the pane received the command.
    if ! herdr pane wait-output "$pane" --match "$BANNER" --timeout 15000 &>/dev/null; then
        print -u2 "The update did not start in pane $pane."
        return 1
    fi

    print "chezmoi update runs in Herdr pane $pane."
}

stop_apps() {
    pkill 'Keyboard Maestro Engine'
}

open_apps() {
    open -a 'Keyboard Maestro Engine'
}

notify() {
    local msg=$1
    if command -v noti &>/dev/null; then
        noti -m "$msg" -t 'chezmoi update'
    fi
}

wait_for_key() {
    printf 'press any key to finish '
    read -k1 -s
    print
}

handle_result() {
    local exit_code=$1
    if [ $exit_code -ne 0 ]; then
        notify 'failed'
        echo 'Chezmoi update failed.'
    else
        notify 'successful'
        figlet 'chezmoi updated!'
    fi
    wait_for_key
}

run_update() {
    print -- "$BANNER"

    stop_apps

    chezmoi update
    local exit_code=$?

    open_apps
    handle_result $exit_code
}

if [[ -n ${(P)WORKER_ENV:-} ]]; then
    run_update
else
    launch_in_herdr
fi
