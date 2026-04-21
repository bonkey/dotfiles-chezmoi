# Installation

_Note: **DO NOT** install iTerm2, Rectangle, SetApp, Raycast or any other app before. There's plenty in `brew` already._

## Install brew

Check the latest command on https://brew.sh

```shell
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

## Setup brew in shell

```shell
eval "$(/opt/homebrew/bin/brew shellenv)"
```

## Install chezmoi and basic tools

```shell
brew install chezmoi 1password-cli mise gh
gh auth login
```

## Configure chezmoi

```shell
mkdir -p ~/.config/chezmoi
vi ~/.config/chezmoi/chezmoi.toml
```

```toml
[data]
email = "xxx@yyy.zzz"
gpgkey = "XXX"

[edit]
command = "zed"
args = ["--wait", "--new"]

[git]
autoCommit = true
autoPush = true

[diff]
exclude = ["scripts"]

[[textconv]]
pattern = "**/*.kmsync"
command = "/bin/zsh"
args = ["-c", "plutil -convert json -o - - | jq -r --sort-keys"]

[hooks.edit.pre]
command = "bin/secrets-scrubber.py"
args = ["scrub"]

[hooks.edit.post]
command = "bin/secrets-scrubber.py"
args = ["restore"]

[hooks.re-add.pre]
command = "bin/secrets-scrubber.py"
args = ["scrub"]

[hooks.re-add.post]
command = "bin/secrets-scrubber.py"
args = ["restore"]

[hooks.apply.pre]
command = "bin/secrets-scrubber.py"
args = ["scrub"]

[hooks.apply.post]
command = "bin/secrets-scrubber.py"
args = ["restore"]

[hooks.update.pre]
command = "bin/secrets-scrubber.py"
args = ["scrub"]

[hooks.update.post]
command = "bin/secrets-scrubber.py"
args = ["restore"]
```

## Add ssh key from 1password

1. Install 1password
2. Enable CLI and SSH in Developer settings

## Install dotfiles & run scripts

```shell
chezmoi init git@github.com:bonkey/dotfiles-chezmoi.git
chezmoi apply
```
