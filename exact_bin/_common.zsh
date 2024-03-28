if [[ "${TRACE-0}" == "1" ]]; then set -o xtrace ; fi

script_dir=${0:A:h}
script_name=$(basename "${ZSH_SCRIPT:-$0}")

set -o pipefail

if [ -t 1 ]; then IS_TERMINAL=true; fi

color() {
    color=$1
    text=$2
    if [ -n "${IS_TERMINAL}" ]; then
        echo "${color}${text}%f%b%k"
    else
        echo "${text}"
    fi
}

msg_prefix() {
    color "%B%F{blue}" ">>> "
}

log_message() {
    print -P "$(msg_prefix)$*."
}

log_error() {
    print -P "$(msg_prefix)Error: $(color "%B%K{red}%F{white}" $*)."
}

_exec() {
    local cmd exec_start exec_finish
    cmd=$*
    print -P "$(msg_prefix)Executing: $(color %B%K{blue}%F{white} ${cmd})"
    exec_start=$(timestamp)
    eval "${cmd}"
    ret=$?
    exec_finish=$(timestamp)
    elapsed="$(round 3 $(((exec_finish - exec_start) / 1000.0))) s."

    print -P "$(msg_prefix)Elapsed: $(color %B%F{blue} $elapsed)"
    if [[ $ret -ne 0 ]]; then
        print -P "$(msg_prefix)Error executing: $(color "%B%K{red}%F{white}" $cmd). Check the output above and run it again"
        if [[ "$script_name" != "_common.zsh" ]]; then 
            exit $ret
        else
            return $ret
        fi
    fi
}

timestamp() {
    print -P '%D{%s%3.}'
}

round() {
    printf "%.${1}f" $2
}

is_recently_modified() {
    local max_mtime min_mtime file is_modified

    max_mtime=12h
    min_mtime=5m
    file=$1

    test -z "$(find $file -mtime -${max_mtime} -mtime "+${min_mtime}" 2>/dev/null)"
    is_modified=$?

    if [[ $is_modified -eq 1 ]]; then
        return 0
    else
        return 1
    fi
}

exec_unless_recently_modified() {
    local file cmd
    file=$1
    cmd=$2

    if is_recently_modified "$file" ; then
        print -P "$(msg_prefix)Command '$cmd' recently run, skipping (based on $file)."
    else
        _exec $cmd
        touch $file
    fi
}

realpath() { for f in "$@"; do echo ${f}(:A); done }

tsrc() { for src in $* ; test -s "$src" && source "$src" }

eval_managers() {
    if [ -x /opt/homebrew/bin/brew ]; then # For Apple M1
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then # For Intel
        eval "$(/usr/local/bin/brew shellenv)"
    else
        echo "warning: brew not found"
    fi

    if /usr/bin/which -s mise; then
        eval "$(mise activate zsh)"
    elif /usr/bin/which -s rbenv ; then
        if [[ -z "$RBENV_SHELL" ]]; then
            export RBENV_ROOT=$HOME/.rbenv
            eval "$(rbenv init --no-rehash -)"
            (rbenv rehash &) 2>/dev/null
        fi
    else
        echo "warning: mise or rbenv not found"
    fi

    if /usr/bin/which -s pyenv ; then
        if [[ -z "$PYENV_SHELL" ]]; then
            eval "$(pyenv init -)"
        fi
    else
        echo "warning: pyenv not found"
    fi

    tsrc "$HOME/.bun/_bun"

    if /usr/bin/which -s xcenv; then
        if [[ -z "$XCENV_SHELL" ]]; then
            eval "$(xcenv init -)"
        fi
    fi
}

_eval_for_cmd() {
    cmd=$1
    shift

    if /usr/bin/which -s $cmd; then
        output=$(eval "$@")
        eval "$output"
    fi
}