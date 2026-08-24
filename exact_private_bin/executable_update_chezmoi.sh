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

launch_in_herdr() {
    if ! command -v herdr &>/dev/null; then
        print -u2 'herdr is not installed.'
        return 1
    fi

    if ! ensure_herdr_server; then
        print -u2 'Cannot reach a Herdr server.'
        return 1
    fi

    local workspace pane
    workspace=$(herdr workspace create --label "$WORKSPACE_LABEL" --cwd "$HOME" --focus) || return 1
    pane=$(print -r -- "$workspace" | jq -r '.result.root_pane.pane_id')

    # The pane shell needs a moment before it reads typed input.
    sleep 1
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
    open -a iTerm
}

notify() {
    local msg=$1
    if command -v noti &>/dev/null; then
        noti -m "$msg" -t 'chezmoi update'
    fi
}

close_session() {
    printf 'close session? [Y/n] '
    local answer
    read -k1 answer
    print
    [[ $answer == [nN] ]] && return
    if [[ -n ${HERDR_WORKSPACE_ID:-} ]]; then
        herdr workspace close "$HERDR_WORKSPACE_ID" &>/dev/null
    fi
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
    close_session
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
