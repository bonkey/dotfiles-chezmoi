#!/usr/bin/env zsh -l

stop_apps() {
    pkill 'Keyboard Maestro Engine'
}

open_apps() {
    open -a 'Keyboard Maestro Engine'
    open -a iTerm
}

countdown() {
    figlet 'chezmoi updated!'
    for i in {5..1}; do
        figlet $i
        sleep 1
    done
}

notify() {
    local msg=$1
    if command -v noti &>/dev/null; then
        noti -m "$msg" -t 'chezmoi update'
    fi
}

handle_result() {
    local exit_code=$1
    if [ $exit_code -ne 0 ]; then
        notify 'failed'
        echo "Chezmoi update failed. Press any key to exit..."
        read -k1
    else
        notify 'successful'
        countdown
    fi
}

stop_apps

chezmoi update
CHEZMOI_EXIT_CODE=$?

open_apps
handle_result $CHEZMOI_EXIT_CODE
