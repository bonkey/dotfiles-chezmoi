#!/usr/bin/env python3

import json
import sys
import os
import argparse
import subprocess
import curses

CONFIG_FILE = os.path.expanduser("~/.config/opencode/opencode.json")

PRESETS = {
    "search": ['ref', "tavily"],
    "memory": ['basic-memory-cloud'],
    "research": ["exa", "deepwiki", "firecrawl"],
    "local-code-research": ["chunkhound"],
    "ios-dev": ["mobile-mcp", "simctl-mcp", "xcodebuild-mcp", "peekaboo"],
    "ios-doc": ['sosumi'],
    "ios-strings": ['xcstrings-crud'],
    "atlassian": ["atlassian"],
    "semantic-code-retrival": ['serena'],
    "web-dev": ["vibium"],
    "cli-dev": ["shellwright"],
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, 'r') as f:
        content = f.read()
    try:
        return json.loads(content)
    except Exception as e:
        print(f"Error parsing {CONFIG_FILE}: {e}")
        sys.exit(1)

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        f.write(json.dumps(config, indent=2))

def list_mcps():
    print("Presets:")
    for name, mcps in PRESETS.items():
        print(f"  - {name}: {' '.join(mcps)}")
    print("\nDefined MCPs (from config):")
    config = load_config()
    mcps = config.get("mcp", {})
    if not mcps:
        print("  No MCPs found.")
    for name, data in mcps.items():
        enabled = data.get("enabled", True)
        print(f"  - {name} (enabled: {str(enabled).lower()})")

def interactive_menu(stdscr, config):
    curses.curs_set(0)
    preset_names = list(PRESETS.keys())
    mcp_states = config.get("mcp", {})

    # Initial selection: if any MCP in a preset is enabled, consider it selected
    selected = [
        any(mcp_states.get(mcp, {}).get("enabled", False) for mcp in PRESETS[name])
        for name in preset_names
    ]

    current_row = 0
    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, "OpenCode MCP Manager", curses.A_BOLD)
        stdscr.addstr(1, 0, "Space: toggle | Enter: apply & start | q: quit")

        for i, name in enumerate(preset_names):
            box = "[x]" if selected[i] else "[ ]"
            mcp_list = ", ".join(PRESETS[name])
            label = f"{box} {name} ({mcp_list})"
            if i == current_row:
                stdscr.addstr(i + 3, 2, label, curses.A_REVERSE)
            else:
                stdscr.addstr(i + 3, 2, label)

        stdscr.refresh()
        key = stdscr.getch()

        if key == curses.KEY_UP:
            current_row = (current_row - 1) % len(preset_names)
        elif key == curses.KEY_DOWN:
            current_row = (current_row + 1) % len(preset_names)
        elif key == ord(' '):
            selected[current_row] = not selected[current_row]
        elif key in (10, 13):  # Enter key
            en = [preset_names[i] for i, val in enumerate(selected) if val]
            dis = [preset_names[i] for i, val in enumerate(selected) if not val]
            return en, dis
        elif key == ord('q'):
            return None, None

def main():
    parser = argparse.ArgumentParser(description="OpenCode MCP Manager")
    parser.add_argument("-e", "--enable", nargs="+", metavar="PRESET", help="Enable presets")
    parser.add_argument("-d", "--disable", nargs="+", metavar="PRESET", help="Disable presets")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactive selection")
    parser.add_argument("-l", "--list", action="store_true", help="List status")
    parser.add_argument("-ns", "--no-start", action="store_true", help="Skip opencode start")

    args, unknown = parser.parse_known_args()

    if args.list:
        list_mcps()
        return

    config = load_config()
    if "mcp" not in config: config["mcp"] = {}

    to_enable = args.enable or []
    to_disable = args.disable or []

    if args.interactive:
        en, dis = curses.wrapper(interactive_menu, config)
        if en is None: return
        to_enable, to_disable = en, dis

    updated = set()
    def apply_state(names, state):
        for name in names:
            if name in PRESETS:
                for mcp in PRESETS[name]:
                    if mcp in config["mcp"]:
                        config["mcp"][mcp]["enabled"] = state
                        updated.add(mcp)
            else:
                print(f"Warning: Preset '{name}' not found.")

    apply_state(to_enable, True)
    apply_state(to_disable, False)

    if updated:
        save_config(config)

    if not args.no_start:
        # Start opencode with -s as requested
        subprocess.run(["opencode"] + unknown)

if __name__ == "__main__":
    main()
