#!/usr/bin/env zsh
# Populates $POSH_PR_STATUS and $POSH_PR_URL for the oh-my-posh PR segment.
# Refresh is fire-and-forget so the prompt never blocks. Cache lives in
# $XDG_CACHE_HOME/posh-pr-status, keyed per repo+branch, TTL configurable.

POSH_PR_STATUS_TTL=${POSH_PR_STATUS_TTL:-15}
POSH_PR_STATUS_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/posh-pr-status"

# Nerd Font codepoints: U+F044 pencil, U+F00D x, U+F254 hourglass,
# U+F00C check, U+F164 thumbs-up, U+F165 thumbs-down, U+F06E eye.
typeset -g _POSH_PR_JQ='select(.number) | ("#\(.number)"
  + (if .isDraft then " " else "" end)
  + (if (.statusCheckRollup // []) == [] then ""
     elif any(.statusCheckRollup[]; .conclusion == "FAILURE" or .conclusion == "CANCELLED") then " "
     elif any(.statusCheckRollup[]; (.status == "COMPLETED") | not) then " "
     else " " end)
  + (if .reviewDecision == "APPROVED" then " "
     elif .reviewDecision == "CHANGES_REQUESTED" then " "
     elif .reviewDecision == "REVIEW_REQUIRED" then " "
     else "" end))
  + "\t" + .url'

_posh_pr_status_refresh() {
  local toplevel=$1 branch=$2 cache_file=$3
  local out
  out=$(cd "$toplevel" && gh pr view "$branch" \
    --json number,isDraft,reviewDecision,statusCheckRollup,url \
    -q "$_POSH_PR_JQ" 2>/dev/null)
  print -rn -- "$out" >| "$cache_file"
}

_posh_pr_status_precmd() {
  export POSH_PR_STATUS=""
  export POSH_PR_URL=""

  local toplevel branch
  toplevel=$(git rev-parse --show-toplevel 2>/dev/null) || return
  branch=$(git symbolic-ref --quiet --short HEAD 2>/dev/null) || return

  mkdir -p "$POSH_PR_STATUS_DIR"
  local key="${toplevel}#${branch}"
  local hash
  hash=$(print -rn -- "$key" | shasum -a 1 | cut -c1-16)
  local cache_file="$POSH_PR_STATUS_DIR/$hash"

  if [[ -f $cache_file ]]; then
    local line
    line=$(<"$cache_file")
    if [[ -n $line ]]; then
      POSH_PR_STATUS=${line%%$'\t'*}
      POSH_PR_URL=${line#*$'\t'}
    fi
  fi

  if [[ -f $cache_file ]]; then
    local mtime
    mtime=$(stat -f %m "$cache_file" 2>/dev/null) || return
    (( EPOCHSECONDS - mtime < POSH_PR_STATUS_TTL )) && return
  fi

  # Bump mtime first so concurrent prompts do not all fork gh.
  touch "$cache_file"
  { _posh_pr_status_refresh "$toplevel" "$branch" "$cache_file" } &|
}

zmodload zsh/datetime 2>/dev/null

autoload -Uz add-zsh-hook
add-zsh-hook precmd _posh_pr_status_precmd
