#!/usr/bin/env zsh -l

function open_applications {
    open -a 'Keyboard Maestro Engine'
    open -a iTerm
}

function countdown() {
    for i in {5..1}; do
        figlet $i
        sleep 1
    done
}

pkill 'Keyboard Maestro Engine'

chezmoi update && open_applications && countdown
