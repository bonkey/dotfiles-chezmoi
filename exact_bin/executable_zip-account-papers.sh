#!/bin/zsh

test -z "$1" && echo "Usage: $0 <dir_to_zip>" exit 1

dir=$1

zip -r $dir.zip $dir -x \*.pages \*/.DS_Store \*/Icon\*
