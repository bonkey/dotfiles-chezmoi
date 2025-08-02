#!/usr/bin/env zsh

settings=".local/share/chezmoi/dot_config/zed/private_settings.json"
mode="${1:-}"

typeset -A secrets
secrets=(
  '.context_servers["api-supermemory-ai"].env.SUPERMEMORY_API_KEY' 'op://Private/lk3cxlvcjdbti27r7ivrcj646y/SUPERMEMORY_API_KEY'
  '.context_servers["mcp-server-brave-search"].settings.brave_api_key' 'op://Private/lk3cxlvcjdbti27r7ivrcj646y/BRAVE_API_KEY'
)

jq_script="."

for key in "${(@k)secrets}"; do
  secret_ref="${secrets[$key]}"

  if [[ "$mode" == "scrub" ]]; then
    echo "Scrubbing: $key"
    jq_script+=" | $key = null"
  elif [[ "$mode" == "restore" ]]; then
    echo "Restoring: $key"
    value="$(op read "$secret_ref")"
    escaped_value=$(printf '%s' "$value" | jq -R '.')
    jq_script+=" | $key = $escaped_value"
  else
    echo "Usage: $0 scrub|restore" >&2
    exit 1
  fi
done

tmp=$(mktemp -t settings)
echo "Updating $settings with $tmp"
jq "$jq_script" "$settings" > "$tmp"
cp -v "$tmp" "$settings"
