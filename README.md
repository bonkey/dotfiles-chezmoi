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

## Install chezmoi

```shell
brew install chezmoi
```

## Add ssh key from 1password

1. Install 1password
2. Enable CLI and SSH in Developer settings
3. Install CLI

```shell
brew install 1password-cli@beta
```

## Install dotfiles & run scripts

Build config

```shell
chezmoi init git@github.com:bonkey/dotfiles-chezmoi.git
```

Install basic files

```shell
chezmoi apply -x scripts \
  --config <(chezmoi cat-config | sed '/^\[hooks\./,/^$/d') --config-format toml \
  --persistent-state ~/.config/chezmoi/chezmoistate.boltdb
```

Run all installation scripts

```shell
chezmoi apply

```
