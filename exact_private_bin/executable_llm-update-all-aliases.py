#!/usr/bin/env python3
"""
Script to update LLM model aliases to create model_name-latest aliases.
Uses simple regex patterns to detect model families and versions.
"""

import subprocess
import re
import argparse
from typing import Dict, List, Tuple, Optional
import sys
import json
import os


def run_command(cmd: List[str], verbose: bool = False) -> str:
    """Run a command and return its output."""
    if verbose:
        print(f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout.strip()

        if verbose and output:
            print(f"Output: {output}")

        return output
    except subprocess.CalledProcessError as e:
        print(f"Error running command {' '.join(cmd)}: {e}")
        if verbose and e.stderr:
            print(f"Error output: {e.stderr}")
        return ""


def parse_models(verbose: bool = False) -> Dict[str, List[Tuple[str, List[str]]]]:
    """Parse llm models output and return a dict of provider -> [(model_name, aliases)]."""
    output = run_command(["llm", "models"], verbose)
    if not output:
        return {}

    models = {}

    for line in output.split("\n"):
        line = line.strip()
        if not line or line.startswith("Default:"):
            continue

        # Parse model line: "Provider: model_name (aliases: alias1, alias2)"
        if ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                provider = parts[0].strip()
                model_part = parts[1].strip()

                # Initialize provider if not seen before
                if provider not in models:
                    models[provider] = []

                # Split on "(aliases:" to separate model name from aliases
                alias_split = model_part.split("(aliases:", 1)
                model_name = alias_split[0].strip()

                aliases = []
                if len(alias_split) > 1:
                    # Extract aliases
                    alias_part = alias_split[1].rstrip(")")
                    aliases = [alias.strip() for alias in alias_part.split(",") if alias.strip()]

                models[provider].append((model_name, aliases))

    return models


def get_aliases_path() -> str:
    """Get the path to aliases.json file."""
    aliases_path_output = run_command(["llm", "aliases", "path"], verbose=False)
    return aliases_path_output.strip() if aliases_path_output else ""

def load_aliases(verbose: bool = False) -> Dict[str, str]:
    """Load user aliases from JSON file."""
    aliases_path = get_aliases_path()
    if not aliases_path or not os.path.exists(aliases_path):
        return {}

    try:
        with open(aliases_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        if verbose:
            print(f"Could not read aliases file: {e}")
        return {}

def save_aliases(aliases: Dict[str, str], verbose: bool = False) -> bool:
    """Save aliases directly to JSON file."""
    aliases_path = get_aliases_path()
    if not aliases_path:
        return False

    try:
        with open(aliases_path, 'w') as f:
            json.dump(aliases, f, indent=4)
        return True
    except IOError as e:
        if verbose:
            print(f"Could not write aliases file: {e}")
        return False

def parse_existing_aliases(verbose: bool = False) -> Dict[str, str]:
    """Get all existing user-created aliases that point to -latest models or end with -latest."""
    user_aliases = load_aliases(verbose)
    if verbose:
        print(f"Found {len(user_aliases)} user-created aliases")

    # Filter for aliases that point to -latest models or end with -latest
    latest_aliases = {}
    for alias_name, target_model in user_aliases.items():
        if "-latest" in target_model or alias_name.endswith("-latest"):
            if verbose:
                print(f"Found removable -latest alias: {alias_name} -> {target_model}")
            latest_aliases[alias_name] = target_model

    return latest_aliases


def should_exclude_model(model_name: str) -> bool:
    """Determine if we should exclude this model from consideration."""
    exclude_patterns = [
        r"-\d{4}-\d{2}-\d{2}",  # Date patterns like -2024-12-17
        r"-preview",
        r"-exp$",  # Only exclude -exp at end, not thinking-exp
        r"-experimental",
        r"-alpha",
        r"-beta",
        r"-rc\d*",
        r"-dev",
        r"-nightly",
        r"-canary",
        r"-edge",
        r"-latest",
    ]

    for pattern in exclude_patterns:
        if re.search(pattern, model_name, re.IGNORECASE):
            return True
    return False


def extract_model_family(model_name: str) -> Optional[str]:
    """Extract the base model family name using regex pattern."""
    # Remove provider prefix if present
    if "/" in model_name:
        model_name = model_name.split("/", 1)[1]

    # Special handling for thinking models - normalize the exp-date suffix
    thinking_pattern = r"(.+)-thinking-exp-[\d-]+"
    thinking_match = re.match(thinking_pattern, model_name, re.IGNORECASE)
    if thinking_match:
        base_model = thinking_match.group(1)
        # Extract the base family and add thinking
        if "/" in base_model:
            base_model = base_model.split("/", 1)[1]
        base_family_match = re.match(r"(?P<family>[a-z/]+)-(?P<version>[0-9]+[.-][0-9]+)-(?P<type>[a-z-]+)", base_model, re.IGNORECASE)
        if base_family_match:
            family = base_family_match.group('family')
            base_type = base_family_match.group('type')
            return f"{family}-{base_type}-thinking"

    # Main pattern: model_family-version-model_type
    pattern = r"(?P<model_family>[a-z/]+)-(?P<version>[0-9]+[.-][0-9]+)-(?P<model_type>[a-z]+(?:-[a-z]+)*)"
    match = re.match(pattern, model_name, re.IGNORECASE)

    if match:
        family = match.group('model_family')
        model_type = match.group('model_type')

        # Exclude meaningless suffixes that appear on base models
        meaningless_suffixes = ['turbo', 'preview', 'instruct']
        if model_type.lower() in meaningless_suffixes:
            return None

        # Accept any other model type as meaningful
        return f"{family}-{model_type}"

    # Secondary pattern: model_family-model_type (no version)
    pattern2 = r"(?P<model_family>[a-z/]+)-(?P<model_type>[a-z-]+)$"
    match2 = re.match(pattern2, model_name, re.IGNORECASE)

    if match2:
        family = match2.group('model_family')
        model_type = match2.group('model_type')

        # Exclude meaningless suffixes
        meaningless_suffixes = ['turbo', 'preview', 'instruct']
        if model_type.lower() in meaningless_suffixes:
            return None

        return f"{family}-{model_type}"

    return None


def get_version_key(model_name: str) -> Tuple[int, int, int, str]:
    """Extract version for sorting - higher versions come first."""
    # Prioritize base models over mini/nano variants (0 = base, 1 = variant)
    is_variant = 1 if any(x in model_name for x in ['-mini', '-nano', '-instruct']) else 0

    # Extract version numbers
    version_match = re.search(r"(\d+)\.?(\d*)", model_name)
    major = int(version_match.group(1)) if version_match else 0
    minor = int(version_match.group(2)) if version_match and version_match.group(2) else 0

    return (is_variant, -major, -minor, model_name)


def find_latest_models(models: Dict[str, List[Tuple[str, List[str]]]]) -> Dict[str, str]:
    """Find the latest version of each model family."""
    family_models = {}

    # Group models by family
    for provider, model_list in models.items():
        for model_name, aliases in model_list:
            # Skip excluded models
            if should_exclude_model(model_name):
                continue

            # Skip models without aliases (not commonly used)
            if not aliases:
                continue

            family = extract_model_family(model_name)
            if family:
                # Use model name with correct provider prefix
                if model_name.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")):
                    full_model_name = model_name
                elif "/" in model_name:
                    # Already has provider prefix
                    full_model_name = model_name
                else:
                    provider_prefix = provider.split()[0].lower()
                    full_model_name = f"{provider_prefix}/{model_name}"

                if family not in family_models:
                    family_models[family] = []
                family_models[family].append((full_model_name, model_name))

    # Find latest version for each family
    latest_models = {}
    for family, candidates in family_models.items():
        if not candidates:
            continue

        # Sort by version (base models first, then highest version)
        candidates.sort(key=lambda x: get_version_key(x[1]))
        latest_full_name, _ = candidates[0]
        latest_models[family] = latest_full_name

    return latest_models


def create_aliases_batch(new_aliases: Dict[str, str], verbose: bool = False) -> int:
    """Create multiple aliases by updating JSON directly."""
    current_aliases = load_aliases(verbose)

    created_count = 0
    for alias_name, model_name in new_aliases.items():
        # Skip if alias already exists with same target
        if alias_name in current_aliases and current_aliases[alias_name] == model_name:
            if verbose:
                print(f"Skipping {alias_name} -> {model_name} (already exists)")
            continue

        current_aliases[alias_name] = model_name
        if verbose:
            print(f"Adding to JSON: {alias_name} -> {model_name}")
        print(f"\033[32mCreate alias\033[0m \033[36m{alias_name}\033[0m -> \033[33m{model_name}\033[0m")
        created_count += 1

    if created_count > 0:
        if save_aliases(current_aliases, verbose):
            return created_count
        else:
            print("Failed to save aliases to file")
            return 0

    return created_count


def remove_aliases_batch(aliases_to_remove: List[str], verbose: bool = False) -> int:
    """Remove multiple aliases by updating JSON directly."""
    current_aliases = load_aliases(verbose)

    removed_count = 0
    for alias_name in aliases_to_remove:
        if alias_name in current_aliases:
            del current_aliases[alias_name]
            if verbose:
                print(f"Removing from JSON: {alias_name}")
            print(f"\033[31mRemove alias\033[0m \033[36m{alias_name}\033[0m")
            removed_count += 1
        elif verbose:
            print(f"Alias {alias_name} not found in file")

    if removed_count > 0:
        if save_aliases(current_aliases, verbose):
            return removed_count
        else:
            print("Failed to save aliases to file")
            return 0

    return removed_count


def main():
    parser = argparse.ArgumentParser(
        description="Update LLM model aliases to create -latest versions"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Show the actual commands being run"
    )
    parser.add_argument(
        "--remove", action="store_true", help="Remove all existing -latest aliases"
    )
    args = parser.parse_args()

    if args.remove:
        # Remove all existing -latest aliases
        existing_aliases = parse_existing_aliases(args.verbose)
        if not existing_aliases:
            print("No -latest aliases found to remove")
            return 0

        removed_count = remove_aliases_batch(list(existing_aliases.keys()), args.verbose)
        print(f"\nRemoved {removed_count} -latest aliases")
        return 0

    # Create new -latest aliases
    models = parse_models(args.verbose)
    if not models:
        print("No models found or error parsing models")
        return 1

    if args.verbose:
        print(f"Parsed {len(models)} providers:")
        for provider, model_list in models.items():
            print(f"  {provider}: {len(model_list)} models")

    latest_models = find_latest_models(models)
    if args.verbose:
        print(f"\nFound {len(latest_models)} model families:")
        for family, model in latest_models.items():
            print(f"  {family}: {model}")

    # Create new -latest aliases
    new_aliases = {f"{family}-latest": latest_model for family, latest_model in latest_models.items()}

    created_count = create_aliases_batch(new_aliases, args.verbose)
    print(f"\nCreated {created_count} new -latest aliases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
