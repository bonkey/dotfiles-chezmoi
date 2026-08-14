#!/usr/bin/env zsh
# Populates the oh-my-posh PR segment env vars. Refresh is fire-and-forget so
# the prompt never blocks. Cache lives in $XDG_CACHE_HOME/posh-pr-status,
# keyed per repo+branch, TTL configurable.
#
# Emitted env vars:
#   POSH_PR_PREFIX  leading type glyph (rendered plain, NOT linked)
#   POSH_PR_NUMBER  "#<n>" (the only part the theme turns into a link)
#   POSH_PR_SUFFIX  checks/review/conflict glyphs (rendered plain, NOT linked)
#   POSH_PR_URL     PR url (link target for the number)
#   POSH_PR_COLOR   oh-my-posh palette ref for the segment background

POSH_PR_STATUS_TTL=${POSH_PR_STATUS_TTL:-15}
POSH_PR_STATUS_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/posh-pr-status"

# Nerd Font codepoints:
#   prefix: U+EB40 git-pull-request (ready), U+F044 pencil (draft)
#   checks: U+F00D x (fail), U+F254 hourglass (pending), U+F00C check (pass)
#   review: U+F164 thumbs-up (approved), U+F165 thumbs-down (changes), U+F06E eye (required)
#   merge:  U+F071 warning triangle (conflict)
# jq \uXXXX escapes render the codepoint; inside this single-quoted string
# the backslashes pass through to jq untouched.
#
# Output is "<prefix>\t<number>\t<suffix>\t<url>\t<color>". The color is an
# oh-my-posh palette ref picked by severity so the most urgent state wins the
# background: fail/conflict > changes-requested > pending > draft > approved.
typeset -g _POSH_PR_JQ='select(.number)
  | (.statusCheckRollup // []) as $cs
  | (if ($cs | length) == 0 then "none"
     elif any($cs[]; .conclusion == "FAILURE" or .conclusion == "CANCELLED") then "fail"
     elif any($cs[]; (.status == "COMPLETED") | not) then "pending"
     else "pass" end) as $check
  | (.mergeable == "CONFLICTING") as $conflict
  | .reviewDecision as $review
  | (if .isDraft then "\uf044" else "\ueb40" end) as $prefix
  | "#\(.number)" as $number
  | ((if $check == "fail" then " \uf00d"
      elif $check == "pending" then " \uf254"
      elif $check == "pass" then " \uf00c"
      else "" end)
     + (if $review == "APPROVED" then " \uf164"
        elif $review == "CHANGES_REQUESTED" then " \uf165"
        elif $review == "REVIEW_REQUIRED" then " \uf06e"
        else "" end)
     + (if $conflict then " \uf071" else "" end)) as $suffix
  | (if $check == "fail" then "p:red"
     elif $conflict then "p:red"
     elif $review == "CHANGES_REQUESTED" then "p:orange"
     elif $check == "pending" then "p:yellow"
     elif .isDraft then "p:grey"
     elif $review == "APPROVED" then "p:green"
     else "p:blue" end) as $color
  | $prefix + "\t" + $number + "\t" + $suffix + "\t" + .url + "\t" + $color'

_posh_pr_status_refresh() {
  local toplevel=$1 branch=$2 cache_file=$3
  local out
  out=$(cd "$toplevel" && gh pr view "$branch" \
    --json number,isDraft,reviewDecision,statusCheckRollup,mergeable,url \
    -q "$_POSH_PR_JQ" 2>/dev/null)
  # Write to a temp file and rename so a concurrent prompt never reads a
  # half-written line (rename is atomic on the same filesystem).
  local tmp="$cache_file.$$"
  print -rn -- "$out" >| "$tmp" && mv -f "$tmp" "$cache_file"
}

_posh_pr_status_precmd() {
  export POSH_PR_PREFIX=""
  export POSH_PR_NUMBER=""
  export POSH_PR_SUFFIX=""
  export POSH_PR_URL=""
  export POSH_PR_COLOR=""

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
    # New 5-field format "<prefix>\t<number>\t<suffix>\t<url>\t<color>" (4
    # tabs). Older cache files are ignored; the background refresh rewrites them.
    if [[ $line == *$'\t'*$'\t'*$'\t'*$'\t'* ]]; then
      local rest
      POSH_PR_PREFIX=${line%%$'\t'*};  rest=${line#*$'\t'}
      POSH_PR_NUMBER=${rest%%$'\t'*};  rest=${rest#*$'\t'}
      POSH_PR_SUFFIX=${rest%%$'\t'*};  rest=${rest#*$'\t'}
      POSH_PR_URL=${rest%%$'\t'*};     rest=${rest#*$'\t'}
      POSH_PR_COLOR=$rest
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
