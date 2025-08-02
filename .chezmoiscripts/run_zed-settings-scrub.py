#!/usr/bin/env python3

"""
Enhanced Zed settings scrubber with 1Password integration
Automatically detects secrets from 1Password and handles scrubbing/restoration

Requires adding in ~/.config/chezmoi/chezmoi.toml:

```
[hooks.re-add.pre]
    command = ".local/share/chezmoi/.chezmoiscripts/run_zed-settings-scrub.py"
    args = ["scrub"]

[hooks.re-add.post]
    command = ".local/share/chezmoi/.chezmoiscripts/run_zed-settings-scrub.py"
    args = ["restore"]

[hooks.apply.post]
    command = ".local/share/chezmoi/.chezmoiscripts/run_zed-settings-scrub.py"
    args = ["restore"]
```

"""

import json
import subprocess
import sys
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

# Configuration
ITEM_ID = "lk3cxlvcjdbti27r7ivrcj646y"
SETTINGS_PATH = Path.home() / ".config" / "zed" / "settings.json"


def run_command(cmd, capture_output=True, check=True):
    """Run a shell command and return the result."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=capture_output, text=True, check=check
        )
        return result.stdout.strip() if capture_output else None
    except subprocess.CalledProcessError as e:
        if capture_output:
            print(f"Command failed: {cmd}")
            print(f"Error: {e.stderr}")
        return None


def check_dependencies():
    """Check if required tools are available."""
    for tool in ["op", "jq"]:
        if not shutil.which(tool):
            print(f"Error: {tool} is required but not installed")
            sys.exit(1)


def get_1password_fields():
    """Get all fields from the 1Password item."""
    print(f"Fetching 1Password item: {ITEM_ID}")

    # Get the item JSON
    item_json = run_command(f'op item get "{ITEM_ID}" --format=json')
    if not item_json:
        print(
            "Error: Failed to retrieve 1Password item. Make sure you're signed in to 1Password CLI"
        )
        sys.exit(1)

    try:
        item_data = json.loads(item_json)
    except json.JSONDecodeError:
        print("Error: Invalid JSON from 1Password item")
        sys.exit(1)

    # Extract fields with labels, references, and values
    fields = {}
    for field in item_data.get("fields", []):
        if (
            field.get("type") in ["STRING", "CONCEALED"]
            and field.get("label")
            and field.get("value")
        ):
            fields[field["label"]] = {
                "reference": field.get("reference"),
                "value": field["value"],
            }

    return fields


def read_settings():
    """Read the settings file."""
    if not SETTINGS_PATH.exists():
        print(f"Error: Settings file not found: {SETTINGS_PATH}")
        sys.exit(1)

    try:
        with open(SETTINGS_PATH, "r") as f:
            return f.read()
    except Exception as e:
        print(f"Error reading settings file: {e}")
        sys.exit(1)


def write_settings(content):
    """Write content to the settings file."""
    try:
        with open(SETTINGS_PATH, "w") as f:
            f.write(content)
    except Exception as e:
        print(f"Error writing settings file: {e}")
        sys.exit(1)


def validate_json(content):
    """Validate that content is valid JSON5/JSONC (with comments and trailing commas)."""
    import re

    # Remove single-line comments (// ...)
    content = re.sub(r'//.*?(?=\n|$)', '', content)

    # Remove multi-line comments (/* ... */)
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)

    # Remove trailing commas before closing brackets/braces
    content = re.sub(r',(\s*[}\]])', r'\1', content)

    try:
        json.loads(content)
        return True
    except json.JSONDecodeError:
        return False


def create_backup():
    """Create a backup of the settings file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = SETTINGS_PATH.with_suffix(f".json.backup.{timestamp}")
    shutil.copy2(SETTINGS_PATH, backup_path)
    print(f"Created backup: {backup_path}")
    return backup_path

def remove_backup(backup_path):
    """Remove a backup file."""
    if backup_path and backup_path.exists():
        backup_path.unlink()
        print(f"Removed backup: {backup_path}")


def check_mode(fields, verbose=False):
    """Check which secrets are present in settings."""
    settings_content = read_settings()
    found_count = 0

    print(f"Processing {len(fields)} labels...")
    if verbose:
        print(f"Labels: {list(fields.keys())}")

    for label, field_data in fields.items():
        if verbose:
            print(f"Checking: {label}")

        placeholder = f"<{label}_REDACTED>"
        secret_value = field_data["value"]

        # First check if placeholder already exists (fast check)
        if placeholder in settings_content:
            print(f"✓ Found placeholder: {label} (already redacted)")
            found_count += 1
        else:
            # Check if actual secret value exists
            if verbose:
                print(f"  Secret length: {len(secret_value)} characters")

            if secret_value in settings_content:
                print(f"✓ Found secret value: {label} (needs redaction)")
                found_count += 1
            else:
                if verbose:
                    print(f"  Secret not found in settings")
                    # Show preview of secret
                    if len(secret_value) > 10:
                        preview = f"{secret_value[:3]}...{secret_value[-3:]}"
                    else:
                        preview = f"{secret_value[:2]}..{secret_value[-1:]}"
                    print(f"  Secret preview: {preview}")

                    # Show relevant lines from settings
                    print(f"  Lines in settings mentioning '{label}':")
                    for line in settings_content.split("\n"):
                        if label.lower() in line.lower():
                            print(f"    {line.strip()}")

    print(f"\nCheck complete: {found_count} secrets found in settings file")
    if found_count > 0:
        print("Run with 'scrub' mode to replace them with placeholders")


def scrub_mode(fields, verbose=False):
    """Replace secrets with labeled placeholders."""
    settings_content = read_settings()
    backup_path = create_backup()
    processed_count = 0

    for label, field_data in fields.items():
        secret_value = field_data["value"]

        if verbose:
            print(f"Checking for value of {label} ({len(secret_value)} chars)")

        if secret_value in settings_content:
            print(f"Scrubbing: {label}")
            placeholder = f"<{label}_REDACTED>"
            settings_content = settings_content.replace(secret_value, placeholder)
            processed_count += 1
        elif verbose:
            print(f"  Value not found in settings")

    # Validate JSON before writing
    if not validate_json(settings_content):
        print("⚠ Warning: Settings would have invalid JSON. Restoring backup...")
        shutil.copy2(backup_path, SETTINGS_PATH)
        print("Backup restored. Please check your secrets manually.")
        sys.exit(1)

    write_settings(settings_content)

    print(f"\nScrub complete: {processed_count} secrets replaced with placeholders")
    if processed_count > 0:
        print("Run with 'restore' mode to restore the original values")

    # Remove backup since scrub was successful
    remove_backup(backup_path)


def restore_mode(fields, verbose=False):
    """Replace placeholders with actual secrets."""
    settings_content = read_settings()
    backup_path = create_backup()
    processed_count = 0

    for label, field_data in fields.items():
        placeholder = f"<{label}_REDACTED>"

        if placeholder in settings_content:
            secret_value = field_data["value"]
            print(f"Restoring: {label}")
            settings_content = settings_content.replace(placeholder, secret_value)
            processed_count += 1

    # Validate JSON before writing
    if not validate_json(settings_content):
        print("⚠ Warning: Settings would have invalid JSON. Restoring backup...")
        shutil.copy2(backup_path, SETTINGS_PATH)
        print("Backup restored. Please check your secrets manually.")
        sys.exit(1)

    write_settings(settings_content)

    print(
        f"\nRestore complete: {processed_count} placeholders replaced with actual values"
    )

    # Remove backup since restore was successful
    remove_backup(backup_path)


def main():
    """Main function."""
    if len(sys.argv) < 2 or sys.argv[1] not in ["check", "scrub", "restore"]:
        print("Usage: python3 run_zed-settings-scrub.py <mode> [verbose]")
        print("Modes:")
        print("  check   - Check which secrets are present in settings")
        print("  scrub   - Replace secrets with labeled placeholders")
        print("  restore - Replace placeholders with actual secrets")
        print("Options:")
        print("  verbose - Show detailed debugging information")
        sys.exit(1)

    mode = sys.argv[1]
    verbose = len(sys.argv) > 2 and sys.argv[2] == "verbose"

    # Check dependencies
    check_dependencies()

    # Get 1Password fields
    fields = get_1password_fields()

    if not fields:
        print("Error: No valid fields found in 1Password item")
        sys.exit(1)

    print(f"Found {len(fields)} secret fields in 1Password item")

    # Execute the requested mode
    if mode == "check":
        check_mode(fields, verbose)
    elif mode == "scrub":
        scrub_mode(fields, verbose)
    elif mode == "restore":
        restore_mode(fields, verbose)


if __name__ == "__main__":
    main()
