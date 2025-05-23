#!/usr/bin/env zsh -i

function read_key {
    local oldstty=$(stty -g)
    stty -icanon -echo min 1 time 0
    local char=$(dd bs=1 count=1 2>/dev/null)
    stty $oldstty
    echo $char
}

function kill_applications {
    if [[ "$__CFBundleIdentifier" != "com.googlecode.iterm2" ]]; then
        echo -n "Quit iTerm2? (y/n) "
        response=$(read_key)
        echo
        [[ $response == "y" ]] && pkill iTerm
    fi

    pkill 'Keyboard Maestro Engine'
}

function open_applications {
    open -a 'Keyboard Maestro Engine'
}

function countdown() {
    for i in {5..1}; do
        figlet $i
        sleep 1
    done
}

kill_applications && chezmoi update && open_applications && countdown
