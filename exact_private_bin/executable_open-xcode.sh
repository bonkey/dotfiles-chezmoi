#!/usr/bin/env zsh
# Open an Xcode project, workspace, or Package.swift with the selected Xcode.
#
# Usage:
#   open-xcode.sh [-r] [PROJECT]   open PROJECT, or the first *.xcworkspace / *.xcodeproj /
#                                  Package.swift in the current directory        (alias: .xc)
#   open-xcode.sh -s|--search [-r] search subdirectories for the nearest *.xcworkspace /
#                                  *.xcodeproj and open it                        (alias: .x)
#   open-xcode.sh -p|--print ...   print the project that would be opened, do not open it
#                                  (alias: find-xcode-proj)
#   open-xcode.sh -h|--help
#
# Options:
#   -r, --resolve   clean and resolve package dependencies first (.xcr from ~/.aliases)
#
# Honors a .xcode-version file in the current directory by selecting that Xcode
# with `xcodes select` before opening.

script_path=${0:A}
source "${script_path:h}/_common.zsh"

usage() {
  sed -n '2,17p' "$script_path" | sed 's/^# \{0,1\}//'
}

# Locate a project in the current directory (or validate the given one).
find_project_here() {
  local given=$1 candidates
  if [[ -n "$given" ]]; then
    [[ -e "$given" ]] || { log_error "'$given' not found" >&2; return 1; }
    echo "$given"
    return
  fi
  candidates=(*.xcworkspace(N) *.xcodeproj(N) Package.swift(N))
  if (( ${#candidates} == 0 )); then
    log_error "No xcworkspace/xcodeproj/Package.swift found in $(pwd)" >&2
    return 1
  fi
  echo "${candidates[1]}"
}

# Search subdirectories; prefer the shallowest match, and a workspace over a project.
find_project_recursive() {
  local -a found
  found=("${(@f)$(fd --type d --hidden '\.(xcworkspace|xcodeproj)$' 2>/dev/null)}")
  found=("${(@)found%/}")           # fd prints directories with a trailing slash
  found=("${(@)found:#}")
  found=("${(@)found:#*.xcodeproj/*}")  # skip Foo.xcodeproj/project.xcworkspace
  if (( ${#found} == 0 )); then
    find_project_here ""
    return
  fi
  local best="" best_key="" p depth kind key
  for p in "${found[@]}"; do
    depth=${#${p//[^\/]/}}
    kind=1; [[ "$p" == *.xcworkspace ]] && kind=0
    key="${depth}${kind}"
    if [[ -z "$best" || "$key" < "$best_key" ]]; then
      best=$p; best_key=$key
    fi
  done
  echo "$best"
}

select_xcode_from_file() {
  [[ -f .xcode-version ]] || return 0
  local wanted
  wanted=$(<.xcode-version)
  if ! xcrun xcodebuild -version 2>/dev/null | head -1 | grep -q "$wanted"; then
    log_message "Selecting Xcode ${wanted}"
    xcodes select "$wanted"
  fi
}

xcode_version() {
  xcrun xcodebuild -version 2>/dev/null | head -1 | sed 's/.*Xcode \(.*\)/\1/'
}

main() {
  local search=false print=false resolve=false project="" arg

  for arg in "$@"; do
    case "$arg" in
      -h|--help)    usage; return 0 ;;
      -s|--search)  search=true ;;
      -p|--print)   print=true ;;
      -r|--resolve) resolve=true ;;
      -*)           log_error "Unknown option '$arg'"; usage; return 2 ;;
      *)            [[ -z "$project" ]] && project=$arg ;;
    esac
  done

  if [[ "$search" == true ]]; then
    project=$(find_project_recursive) || return 1
  else
    project=$(find_project_here "$project") || return 1
  fi

  if [[ "$print" == true ]]; then
    echo "$project"
    return 0
  fi

  select_xcode_from_file

  local xcode_app
  xcode_app=$(xcode-select -p)
  xcode_app=${xcode_app%/Contents/Developer}
  log_message "Opening ${project} with ${xcode_app} ($(color '%B%F{green}' "$(xcode_version)"))"

  if [[ "$resolve" == true ]]; then
    source "$HOME/.aliases"
    .xcr "$project"
  fi

  open -a "$xcode_app" "$project"
}

main "$@"
