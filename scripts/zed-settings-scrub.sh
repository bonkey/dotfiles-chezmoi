#!/bin/zsh

set -euo pipefail

settings="$HOME/.config/zed/settings.json"
tmp="$settings.tmp"
mode="${1:-}"

# Define command paths
bin_prefix="${HOMEBREW_PREFIX}/bin"
op_cmd="${bin_prefix}/op"
jq_cmd="${bin_prefix}/jq"

# Define paths and corresponding secrets
typeset -A paths_and_secrets
paths_and_secrets=(
  '.context_servers["api-supermemory-ai"].env.SUPERMEMORY_API_KEY' 'op://Private/lk3cxlvcjdbti27r7ivrcj646y/SUPERMEMORY_API_KEY'
  '.context_servers["mcp-server-brave-search"].settings.brave_api_key' 'op://Private/lk3cxlvcjdbti27r7ivrcj646y/BRAVE_API_KEY'
)

# Build jq script
jq_script="."

for path in "${(@k)paths_and_secrets}"; do
  secret_ref="${paths_and_secrets[$path]}"
  value="$($op_cmd read "$secret_ref")"
  escaped_value=$(printf '%s' "$value" | $jq_cmd -R '.')

  if [[ "$mode" == "scrub" ]]; then
    jq_script+=" | $path = null"
  elif [[ "$mode" == "restore" ]]; then
    jq_script+=" | $path = $escaped_value"
  else
    echo "Usage: $0 scrub|restore" >&2
    exit 1
  fi
done

$jq_cmd "$jq_script" "$settings" > "$tmp"

# && mv "$tmp" "$settings"
