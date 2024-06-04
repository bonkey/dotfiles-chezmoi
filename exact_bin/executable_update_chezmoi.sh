#!/usr/bin/env zsh -l

read -p "Quit iTerm2? (y/n) " -n 1 -r
[[ $REPLY =~ ^[Yy]$ ]] && pkill iTerm

read -p "Quit Keyboard Maestro Engine? (y/n) " -n 1 -r
[[ $REPLY =~ ^[Yy]$ ]] && pkill 'Keyboard Maestro Engine'

chezmoi update

exit
