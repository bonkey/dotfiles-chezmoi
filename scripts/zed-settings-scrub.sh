#!/bin/zsh

settings="$HOME/.config/zed/settings.json"
tmp=$(mktemp -t settings)
mode="${1:-}"

# Define paths and corresponding secrets
typeset -A paths_and_secrets
paths_and_secrets=(
  '.context_servers["api-supermemory-ai"].env.SUPERMEMORY_API_KEY' 'op://Private/lk3cxlvcjdbti27r7ivrcj646y/SUPERMEMORY_API_KEY'
  '.context_servers["mcp-server-brave-search"].settings.brave_api_key' 'op://Private/lk3cxlvcjdbti27r7ivrcj646y/BRAVE_API_KEY'
)

# Build jq script
jq_script="."

for key in "${(@k)paths_and_secrets}"; do
  secret_ref="${paths_and_secrets[$key]}"

  if [[ "$mode" == "scrub" ]]; then
    jq_script+=" | $key = null"
  elif [[ "$mode" == "restore" ]]; then
    value="$(op read "$secret_ref")"
    escaped_value=$(printf '%s' "$value" | jq -R '.')
    jq_script+=" | $key = $escaped_value"
  else
    echo "Usage: $0 scrub|restore" >&2
    exit 1
  fi
done

jq "$jq_script" "$settings" > "$tmp" && mv "$tmp" "$settings"
