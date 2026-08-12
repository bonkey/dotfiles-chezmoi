#!/bin/bash

source "${HOME}/bin/litra/_litra.zsh"

command="$(echo $0 | /opt/homebrew/bin/sd '.*litra-(.*)\.sh$' '$1')"

eval $command