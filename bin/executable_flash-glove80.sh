#!/bin/zsh

WATCH_DIR="$HOME/Downloads"
FILE_MASK="*.uf2"
LH_VOLUME_NAME="GLV80LHBOOT"
RH_VOLUME_NAME="GLV80RHBOOT"

printf "Monitoring $WATCH_DIR for files matching $FILE_MASK\n"
printf "Press Enter or Esc during volume wait to reset/skip current operation\n"

function wait_for_volume() {
  local vol_name="$1"
  echo "Waiting for volume $vol_name..."
  while [[ ! -d "/Volumes/$vol_name" ]]; do
    if read -t 1 -k key; then
      if [[ "$key" == $'\n' || "$key" == $'\r' || "$key" == $'\e' ]]; then
        echo "\nReset/skip requested. Returning to monitoring..."
        return 2  # Special code for reset/skip
      fi
    fi
  done
  echo "Volume $vol_name mounted."
  return 0
}

function copy_to_volume() {
  local src_file="$1"
  local vol_name="$2"
  local dest="/Volumes/$vol_name/$(basename "$src_file")"
  echo "Copying $(basename "$src_file") to $vol_name..."
  cp "$src_file" "$dest" && echo "Copied to $vol_name."
}

function process_file() {
  local uf2_file="$1"

  # Check if file matches our pattern and exists
  if [[ "$uf2_file" == *".uf2" && -f "$uf2_file" ]]; then
    echo "\nFound: $uf2_file"

    for vol_name in "$RH_VOLUME_NAME" "$LH_VOLUME_NAME"; do
      if ! wait_for_volume "$vol_name"; then
        local code=$?
        if [[ $code -eq 2 ]]; then
          return 2  # Reset requested
        fi
        return 1
      fi
      copy_to_volume "$uf2_file" "$vol_name"
    done

    echo "Done with: $uf2_file"
    rm "$uf2_file"
  fi
  return 0
}

function scan_and_process() {
  # Disable nomatch so that globs that don't match expand to themselves
  setopt +o nomatch
  for uf2_file in "$WATCH_DIR"/*.uf2; do
    # If the glob didn't match, skip
    [[ -f "$uf2_file" ]] || continue

    if ! process_file "$uf2_file"; then
      local code=$?
      if [[ $code -eq 2 ]]; then
        # Reset requested, break and return special code
        return 2
      fi
      break
    fi
  done
  # Restore nomatch option if desired (optional, not strictly necessary here)
  return 0
}

# Check if any matching file exists before monitoring
found_file=0
setopt +o nomatch
for uf2_file in "$WATCH_DIR"/*.uf2; do
  if [[ -f "$uf2_file" ]]; then
    found_file=1
    break
  fi
done
if [[ $found_file -eq 1 ]]; then
  scan_and_process
fi

# Use fswatch to detect any changes, then scan directory for matching files
while true; do
  fswatch "$WATCH_DIR" | while read event; do
    if ! scan_and_process; then
      local code=$?
      if [[ $code -eq 2 ]]; then
        # Reset requested, break out to outer loop to restart monitoring
        break
      fi
    fi
  done
done
