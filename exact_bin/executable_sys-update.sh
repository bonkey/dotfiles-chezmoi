#!/usr/bin/env zsh

echo "Use chezmoi! Exiting..."
exit 0

autoload -U colors && colors

local check_file=.sys-check-ts
local check_time="+5d"

zparseopts -D -E -- c=check \
    b=up_brew g=up_gems p=up_python t=up_tldr n=up_npm d=up_dotfiles z=up_zimfw \
    a=opt_a

if [ -n "$opt_a" -o -z "${check}${up_brew}${up_gems}${up_python}${up_dotfiles}${up_tldr}${up_npma}${up_zimfw}" ]; then
    up_gems=1
    up_brew=1
    up_npm=1
    up_tldr=1
    up_python=1
    up_zimfw=1
    up_dotfiles=1
    touch $HOME/$check_file
fi

stage() {
    echo "### Upgrading $fg_bold[yellow]${1}$reset_color"
}

upgrade_tldr() {
    stage "tldr"
    tldr --verbose --update
}

upgrade_npm() {
    stage "npm"
    npm install npm@latest --location=global
    npm update --location=global
}

update_dotfiles() {
    stage "dotfiles"
    cd $HOME/.dotfiles
    git submodule update --remote --merge --init
    git pull --recurse-submodules -j5
    git add .
    git commit -am "Update $(date +"%Y-%m-%dT%H:%M:%SZ") from ${HOST}"
    git pull -s recursive -X ours --no-edit
    git push
    cd -
}

check() {
    test -n "$(find $HOME -maxdepth 1 -name $check_file -mtime $check_time)" && echo "System not updated since $check_time. Please run sys-update.sh"
    exit 0
}

test -n "$check" && check

sudo chown -R $(whoami) /usr/local/bin
chmod u+w /usr/local/bin

test -n "$up_zimfw" && upgrade_zimfw
test -n "$up_dotfiles" && update_dotfiles
test -n "$up_brew" && upgrade_brew
test -n "$up_gems" && upgrade_gems
test -n "$up_tldr" && upgrade_tldr
test -n "$up_python" && upgrade_python
test -n "$up_npm" && upgrade_npm

exit 0
