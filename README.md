# Installation

_Note: **DO NOT** install iTerm2, Rectangle, SetApp, Raycast or any other app before. There's plenty in `brew` already._

## Install brew

Check the latest command on https://brew.sh

```shell
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

## Setup brew in shell

### Apple Silicon

```shell
eval "$(/opt/homebrew/bin/brew shellenv)"
```

### Intel

```shell
eval "$(/usr/local/bin/brew shellenv)"
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
brew install 1password-cli
```

## Install dotfiles & run scripts

```shell
chezmoi init git@github.com:bonkey/dotfiles-chezmoi.git
chezmoi apply
```
