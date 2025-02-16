#!/usr/bin/env zsh -l

function read_key {
    local oldstty=$(stty -g)
    stty -icanon -echo min 1 time 0
    local char=$(dd bs=1 count=1 2>/dev/null)
    stty $oldstty
    echo $char
}

if [[ "$LC_TERMINAL" != "iTerm2" ]]; then
    echo -n "Quit iTerm2? (y/n) "
    response=$(read_key)
    echo
    [[ $response == "y" ]] && pkill iTerm
fi

pkill 'Keyboard Maestro Engine'

chezmoi update && open -a 'Keyboard Maestro Engine'
