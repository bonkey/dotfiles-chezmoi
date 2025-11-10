#!/usr/bin/env python3

"""
Generic secrets scrubber with 1Password integration
Automatically detects secrets from 1Password and handles scrubbing/restoration
for multiple configuration files

Requires adding in ~/.config/chezmoi/chezmoi.toml:

```
[hooks.re-add.pre]
command = "bin/secrets-scrubber.py"
args = ["scrub"]

[hooks.re-add.post]
command = "bin/secrets-scrubber.py"
args = ["restore"]

[hooks.apply.pre]
command = "bin/secrets-scrubber.py"
args = ["scrub"]

[hooks.apply.post]
command = "bin/secrets-scrubber.py"
args = ["restore"]

[hooks.update.pre]
command = "bin/secrets-scrubber.py"
args = ["scrub"]

[hooks.update.post]
command = "bin/secrets-scrubber.py"
args = ["restore"]
```

"""

import json
import subprocess
import sys
import re
import shutil
from datetime import datetime
from pathlib import Path

# Configuration
ITEM_ID = "lk3cxlvcjdbti27r7ivrcj646y"
ACCOUNT = "bonkey.1password.com"

# Files to scrub (add more files here as needed)
FILES_TO_SCRUB = [
    Path.home() / ".config" / "zed" / "settings.json",
    Path.home() / ".codex" / "config.toml",
]


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

    item_json = run_command(
        f'op item get "{ITEM_ID}" --account {ACCOUNT} --format=json'
    )
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


def read_file(file_path):
    """Read a file."""
    if not file_path.exists():
        print(f"Warning: File not found: {file_path}")
        return None

    try:
        with open(file_path, "r") as f:
            return f.read()
    except Exception as e:
        print(f"Error reading file {file_path}: {e}")
        return None


def write_file(file_path, content):
    """Write content to a file."""
    try:
        with open(file_path, "w") as f:
            f.write(content)
    except Exception as e:
        print(f"Error writing file {file_path}: {e}")
        sys.exit(1)


def validate_json(content):
    """Validate that content is valid JSON5/JSONC (with comments and trailing commas)."""
    content = re.sub(r"(?<=\s)//.*?(?=\n|$)", "", content)
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    content = re.sub(r",(\s*[}\]])", r"\1", content)

    try:
        json.loads(content)
        return True
    except json.JSONDecodeError:
        return False


def create_backup(file_path):
    """Create a backup of a file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = file_path.with_suffix(f"{file_path.suffix}.backup.{timestamp}")
    shutil.copy2(file_path, backup_path)
    print(f"Created backup: {backup_path}")
    return backup_path


def remove_backup(backup_path):
    """Remove a backup file."""
    if backup_path and backup_path.exists():
        backup_path.unlink()
        print(f"Removed backup: {backup_path}")


def check_mode(fields, verbose=False):
    """Check which secrets are present in files."""
    total_found = 0

    for file_path in FILES_TO_SCRUB:
        content = read_file(file_path)
        if content is None:
            continue

        print(f"\n{'='*60}")
        print(f"Checking: {file_path}")
        print(f"{'='*60}")

        found_count = 0
        for label, field_data in fields.items():
            if verbose:
                print(f"Checking: {label}")

            placeholder = f"<{label}_REDACTED>"
            secret_value = field_data["value"]

            if placeholder in content:
                print(f"✓ Found placeholder: {label} (already redacted)")
                found_count += 1
            elif secret_value in content:
                print(f"✓ Found secret value: {label} (needs redaction)")
                found_count += 1
            elif verbose:
                print(f"  Secret not found")
                if len(secret_value) > 10:
                    preview = f"{secret_value[:3]}...{secret_value[-3:]}"
                else:
                    preview = f"{secret_value[:2]}..{secret_value[-1:]}"
                print(f"  Secret preview: {preview}")

                print(f"  Lines mentioning '{label}':")
                for line in content.split("\n"):
                    if label.lower() in line.lower():
                        print(f"    {line.strip()}")

        print(f"Found {found_count} secrets in {file_path.name}")
        total_found += found_count

    print(f"\n{'='*60}")
    print(f"Check complete: {total_found} secrets found across all files")


def scrub_mode(fields, verbose=False):
    """Replace secrets with labeled placeholders in all files."""
    total_processed = 0

    for file_path in FILES_TO_SCRUB:
        content = read_file(file_path)
        if content is None:
            continue

        print(f"\n{'='*60}")
        print(f"Scrubbing: {file_path}")
        print(f"{'='*60}")

        backup_path = create_backup(file_path)
        processed_count = 0
        original_content = content

        for label, field_data in fields.items():
            secret_value = field_data["value"]

            if verbose:
                print(f"Checking for value of {label} ({len(secret_value)} chars)")

            if secret_value in content:
                print(f"Scrubbing: {label}")
                placeholder = f"<{label}_REDACTED>"
                content = content.replace(secret_value, placeholder)
                processed_count += 1
            elif verbose:
                print(f"  Value not found")

        if processed_count > 0:
            is_json = file_path.suffix == ".json"
            if is_json and not validate_json(content):
                print(f"⚠ Warning: File would have invalid JSON. Restoring backup...")
                shutil.copy2(backup_path, file_path)
                print("Backup restored. Please check your secrets manually.")
                continue

            write_file(file_path, content)
            print(f"Scrubbed {processed_count} secrets from {file_path.name}")
            remove_backup(backup_path)
            total_processed += processed_count
        else:
            print(f"No secrets found in {file_path.name}")
            remove_backup(backup_path)

    print(f"\n{'='*60}")
    print(f"Scrub complete: {total_processed} secrets replaced with placeholders")
    if total_processed > 0:
        print("Run with 'restore' mode to restore the original values")


def restore_mode(fields, verbose=False):
    """Replace placeholders with actual secrets in all files."""
    total_processed = 0

    for file_path in FILES_TO_SCRUB:
        content = read_file(file_path)
        if content is None:
            continue

        print(f"\n{'='*60}")
        print(f"Restoring: {file_path}")
        print(f"{'='*60}")

        backup_path = create_backup(file_path)
        processed_count = 0

        for label, field_data in fields.items():
            placeholder = f"<{label}_REDACTED>"

            if placeholder in content:
                secret_value = field_data["value"]
                print(f"Restoring: {label}")
                content = content.replace(placeholder, secret_value)
                processed_count += 1

        if processed_count > 0:
            is_json = file_path.suffix == ".json"
            if is_json and not validate_json(content):
                print(f"⚠ Warning: File would have invalid JSON. Restoring backup...")
                shutil.copy2(backup_path, file_path)
                print("Backup restored. Please check your secrets manually.")
                continue

            write_file(file_path, content)
            print(f"Restored {processed_count} placeholders in {file_path.name}")
            remove_backup(backup_path)
            total_processed += processed_count
        else:
            print(f"No placeholders found in {file_path.name}")
            remove_backup(backup_path)

    print(f"\n{'='*60}")
    print(
        f"Restore complete: {total_processed} placeholders replaced with actual values"
    )


def main():
    """Main function."""
    if len(sys.argv) < 2 or sys.argv[1] not in ["check", "scrub", "restore"]:
        print("Usage: secrets-scrubber.py <mode> [verbose]")
        print("Modes:")
        print("  check   - Check which secrets are present in files")
        print("  scrub   - Replace secrets with labeled placeholders")
        print("  restore - Replace placeholders with actual secrets")
        print("Options:")
        print("  verbose - Show detailed debugging information")
        print(f"\nConfigured files:")
        for file_path in FILES_TO_SCRUB:
            print(f"  - {file_path}")
        sys.exit(1)

    mode = sys.argv[1]
    verbose = len(sys.argv) > 2 and sys.argv[2] == "verbose"

    check_dependencies()

    fields = get_1password_fields()

    if not fields:
        print("Error: No valid fields found in 1Password item")
        sys.exit(1)

    print(f"Found {len(fields)} secret fields in 1Password item")

    if mode == "check":
        check_mode(fields, verbose)
    elif mode == "scrub":
        scrub_mode(fields, verbose)
    elif mode == "restore":
        restore_mode(fields, verbose)


if __name__ == "__main__":
    main()
