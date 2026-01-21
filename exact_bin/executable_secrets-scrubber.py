#!/usr/bin/env python3

"""
Generic secrets scrubber with 1Password integration
Automatically detects secrets from 1Password and handles scrubbing/restoration
for multiple configuration files

Requires adding in ~/.config/chezmoi/chezmoi.toml:

```
[hooks.edit.pre]
command = "bin/secrets-scrubber.py"
args = ["scrub"]

[hooks.edit.post]
command = "bin/secrets-scrubber.py"
args = ["restore"]

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

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ITEM_ID = "lk3cxlvcjdbti27r7ivrcj646y"
ACCOUNT = "bonkey.1password.com"

FILES_TO_SCRUB = [
    Path.home() / ".codex" / "config.toml",
    Path.home() / ".config" / "zed" / "settings.json",
    Path.home() / ".config" / "chunkhound" / "config.json",
    Path.home() / ".config" / "opencode" / "opencode.json",
]

def log(message, verbose):
    if verbose:
        print(message)


def run_command(cmd, capture_output=True, check=True, verbose=False):
    log(f"Running command: {cmd}", verbose)
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=capture_output,
            text=True,
            check=check,
        )
        return result.stdout.strip() if capture_output else None
    except subprocess.CalledProcessError as error:
        if capture_output:
            print(f"Command failed: {cmd}")
            if error.stderr:
                print(error.stderr.strip())
        return None


def check_dependencies():
    for tool in ["op", "jq"]:
        if not shutil.which(tool):
            print(f"Error: {tool} is required but not installed")
            sys.exit(1)


def get_1password_fields(verbose):
    log(f"Fetching 1Password item: {ITEM_ID}", verbose)
    item_json = run_command(
        f'op item get "{ITEM_ID}" --account {ACCOUNT} --format=json', verbose=verbose
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


def read_file(file_path, verbose):
    if not file_path.exists():
        log(f"Warning: File not found: {file_path}", verbose)
        return None

    try:
        with open(file_path, "r") as file:
            return file.read()
    except Exception as error:
        print(f"Error reading file {file_path}: {error}")
        return None


def write_file(file_path, content):
    try:
        with open(file_path, "w") as file:
            file.write(content)
    except Exception as error:
        print(f"Error writing file {file_path}: {error}")
        sys.exit(1)


def validate_json(content):
    content = re.sub(r"(?<=\s)//.*?(?=\n|$)", "", content)
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    content = re.sub(r",(\s*[}\]])", r"\1", content)

    try:
        json.loads(content)
        return True
    except json.JSONDecodeError:
        return False


def create_backup(file_path, verbose):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = file_path.with_suffix(f"{file_path.suffix}.backup.{timestamp}")
    shutil.copy2(file_path, backup_path)
    log(f"Created backup: {backup_path}", verbose)
    return backup_path


def remove_backup(backup_path, verbose):
    if backup_path and backup_path.exists():
        backup_path.unlink()
        log(f"Removed backup: {backup_path}", verbose)


def check_mode(fields, verbose):
    summary = []
    total_found = 0

    for file_path in FILES_TO_SCRUB:
        content = read_file(file_path, verbose)
        if content is None:
            continue

        log("\n" + "=" * 60, verbose)
        log(f"Checking: {file_path}", verbose)
        log("=" * 60, verbose)

        found_labels = []
        for label, field_data in fields.items():
            placeholder = f"<{label}_REDACTED>"
            secret_value = field_data["value"]

            if placeholder in content:
                log(f"✓ Found placeholder: {label} (already redacted)", verbose)
                found_labels.append(label)
            elif secret_value in content:
                log(f"✓ Found secret value: {label} (needs redaction)", verbose)
                found_labels.append(label)
            elif verbose:
                log(f"Secret not found: {label}", verbose)

        summary.append((file_path, found_labels))
        total_found += len(found_labels)
        log(f"Found {len(found_labels)} secrets in {file_path.name}", verbose)

    log("\n" + "=" * 60, verbose)
    log(f"Check complete: {total_found} secrets found across all files", verbose)

    if not verbose:
        for file_path, labels in sorted(summary, key=lambda item: str(item[0])):
            if labels:
                display_path = file_path
                try:
                    display_path = file_path.relative_to(Path.home())
                except ValueError:
                    pass
                print(f"{display_path}: {', '.join(labels)}")


def scrub_mode(fields, verbose):
    summary = []

    for file_path in FILES_TO_SCRUB:
        content = read_file(file_path, verbose)
        if content is None:
            continue

        log("\n" + "=" * 60, verbose)
        log(f"Scrubbing: {file_path}", verbose)
        log("=" * 60, verbose)

        backup_path = create_backup(file_path, verbose)
        processed_labels = []

        for label, field_data in fields.items():
            secret_value = field_data["value"]
            placeholder = f"<{label}_REDACTED>"

            if secret_value in content:
                log(f"Scrubbing: {label}", verbose)
                content = content.replace(secret_value, placeholder)
                processed_labels.append(label)
            elif verbose:
                log(f"Value not found for {label}", verbose)

        if processed_labels:
            is_json = file_path.suffix == ".json"
            if is_json and not validate_json(content):
                print(f"⚠ Warning: File would have invalid JSON. Restoring backup...")
                shutil.copy2(backup_path, file_path)
                print("Backup restored. Please check your secrets manually.")
                continue

            write_file(file_path, content)
            summary.append((file_path, processed_labels))
            log(f"Scrubbed {len(processed_labels)} secrets from {file_path.name}", verbose)
            remove_backup(backup_path, verbose)
        else:
            log(f"No secrets found in {file_path.name}", verbose)
            remove_backup(backup_path, verbose)

    if verbose:
        log("\n" + "=" * 60, verbose)
        if summary:
            log("Scrub summary:", verbose)
            for file_path, labels in sorted(summary, key=lambda item: str(item[0])):
                log(f"{file_path.name} {len(labels)}", verbose)
        else:
            log("No secrets were scrubbed.", verbose)
        log("=" * 60, verbose)
    else:
        for file_path, labels in sorted(summary, key=lambda item: str(item[0])):
            display_path = file_path
            try:
                display_path = file_path.relative_to(Path.home())
            except ValueError:
                pass
            print(f"Scrubbing {display_path}: {', '.join(labels)}")


def restore_mode(fields, verbose):
    summary = []

    for file_path in FILES_TO_SCRUB:
        content = read_file(file_path, verbose)
        if content is None:
            continue

        log("\n" + "=" * 60, verbose)
        log(f"Restoring: {file_path}", verbose)
        log("=" * 60, verbose)

        backup_path = create_backup(file_path, verbose)
        processed_labels = []

        for label, field_data in fields.items():
            placeholder = f"<{label}_REDACTED>"
            if placeholder in content:
                secret_value = field_data["value"]
                log(f"Restoring: {label}", verbose)
                content = content.replace(placeholder, secret_value)
                processed_labels.append(label)

        if processed_labels:
            is_json = file_path.suffix == ".json"
            if is_json and not validate_json(content):
                print(f"⚠ Warning: File would have invalid JSON. Restoring backup...")
                shutil.copy2(backup_path, file_path)
                print("Backup restored. Please check your secrets manually.")
                continue

            write_file(file_path, content)
            summary.append((file_path, processed_labels))
            log(f"Restored {len(processed_labels)} placeholders in {file_path.name}", verbose)
            remove_backup(backup_path, verbose)
        else:
            log(f"No placeholders found in {file_path.name}", verbose)
            remove_backup(backup_path, verbose)

    if verbose:
        log("\n" + "=" * 60, verbose)
        if summary:
            log("Restore summary:", verbose)
            for file_path, labels in sorted(summary, key=lambda item: str(item[0])):
                log(f"{file_path.name} {len(labels)}", verbose)
        else:
            log("No placeholders were restored.", verbose)
        log("=" * 60, verbose)
    else:
        for file_path, labels in sorted(summary, key=lambda item: str(item[0])):
            display_path = file_path
            try:
                display_path = file_path.relative_to(Path.home())
            except ValueError:
                pass
            print(f"Restored {display_path}: {', '.join(labels)}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scrub and restore secrets using 1Password placeholders."
    )
    parser.add_argument("mode", choices=["check", "scrub", "restore"])
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    verbose = args.verbose

    check_dependencies()
    fields = get_1password_fields(verbose)

    if not fields:
        print("Error: No valid fields found in 1Password item")
        sys.exit(1)

    log(f"Found {len(fields)} secret fields in 1Password item", verbose)

    if args.mode == "check":
        check_mode(fields, verbose)
    elif args.mode == "scrub":
        scrub_mode(fields, verbose)
    elif args.mode == "restore":
        restore_mode(fields, verbose)


if __name__ == "__main__":
    main()
