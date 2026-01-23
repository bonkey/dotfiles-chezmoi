#!/usr/bin/env python3

import json
import sys
import os
import argparse
import subprocess
import curses
import copy

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

try:
    import tomli_w
except ModuleNotFoundError:
    tomli_w = None

CLI_CONFIG_DIR = os.path.expanduser("~/.config/cli-mcp")
CLI_CONFIG_FILE = os.path.join(CLI_CONFIG_DIR, "config.json")

def load_cli_config():
    if not os.path.exists(CLI_CONFIG_FILE):
        print(f"Missing config file: {CLI_CONFIG_FILE}")
        sys.exit(1)
    with open(CLI_CONFIG_FILE, "r") as f:
        content = f.read()
    try:
        return json.loads(content)
    except Exception as e:
        print(f"Error parsing {CLI_CONFIG_FILE}: {e}")
        sys.exit(1)

def expand_path(path_value):
    return os.path.expanduser(path_value) if path_value else ""

def get_dict(config, key, label):
    value = config.get(key)
    if not isinstance(value, dict):
        print(f"Invalid or missing {label} in {CLI_CONFIG_FILE}.")
        sys.exit(1)
    return value

def get_tool_cfg(cli_config, tool_name):
    tools = get_dict(cli_config, "tools", "tools")
    tool_cfg = tools.get(tool_name)
    if not isinstance(tool_cfg, dict):
        print(f"Unknown tool: {tool_name}")
        sys.exit(1)
    if not tool_cfg.get("format"):
        print(f"Tool '{tool_name}' is missing 'format'.")
        sys.exit(1)
    if not tool_cfg.get("path"):
        print(f"Tool '{tool_name}' is missing 'path'.")
        sys.exit(1)
    if not tool_cfg.get("command"):
        print(f"Tool '{tool_name}' is missing 'command'.")
        sys.exit(1)
    if "config_node" not in tool_cfg:
        print(f"Tool '{tool_name}' is missing 'config_node'.")
        sys.exit(1)
    return tool_cfg

def get_tool_template(tool_cfg, tool_name):
    template = tool_cfg.get("template")
    if template is None:
        print(f"Tool '{tool_name}' is missing 'template'.")
        sys.exit(1)
    if not isinstance(template, dict):
        print(f"Tool '{tool_name}' template must be an object.")
        sys.exit(1)
    return template

def load_tool_config(tool_cfg):
    config_path = expand_path(tool_cfg.get("path", ""))
    if not config_path or not os.path.exists(config_path):
        return {}
    with open(config_path, "rb") as f:
        content = f.read()
    fmt = tool_cfg.get("format", "json")
    if fmt == "json":
        try:
            return json.loads(content.decode("utf-8"))
        except Exception as e:
            print(f"Error parsing {config_path}: {e}")
            sys.exit(1)
    if fmt == "toml":
        if tomllib is None:
            print("tomllib is required to read TOML configs.")
            sys.exit(1)
        try:
            return tomllib.loads(content.decode("utf-8"))
        except Exception as e:
            print(f"Error parsing {config_path}: {e}")
            sys.exit(1)
    print(f"Unsupported format: {fmt}")
    sys.exit(1)

def save_tool_config(tool_cfg, config):
    config_path = expand_path(tool_cfg.get("path", ""))
    if not config_path:
        print("Tool path is not set.")
        sys.exit(1)
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    fmt = tool_cfg.get("format", "json")
    if fmt == "json":
        with open(config_path, "w") as f:
            f.write(json.dumps(config, indent=2))
        return
    if fmt == "toml":
        if tomli_w is None:
            print("tomli_w is required to write TOML configs.")
            sys.exit(1)
        with open(config_path, "w") as f:
            f.write(tomli_w.dumps(config))
        return
    print(f"Unsupported format: {fmt}")
    sys.exit(1)

def split_path(path_value):
    return [p for p in path_value.split(".") if p]

def get_node(config, path_value, create=False):
    if not path_value:
        return config
    keys = split_path(path_value)
    node = config
    for key in keys:
        if not isinstance(node, dict):
            print(f"Invalid node at '{key}' for path '{path_value}'.")
            sys.exit(1)
        if key not in node:
            if create:
                node[key] = {}
            else:
                return None
        node = node[key]
    return node

def build_fragment(path_value, value):
    if not path_value:
        return value
    keys = split_path(path_value)
    fragment = value
    for key in reversed(keys):
        fragment = {key: fragment}
    return fragment

def format_output(tool_cfg, fragment):
    fmt = tool_cfg.get("format", "json")
    if fmt == "json":
        return json.dumps(fragment, indent=2)
    if fmt == "toml":
        if tomli_w is None:
            print("tomli_w is required to format TOML output.")
            sys.exit(1)
        return tomli_w.dumps(fragment)
    print(f"Unsupported format: {fmt}")
    sys.exit(1)

def copy_to_clipboard(text):
    subprocess.run(["pbcopy"], input=text.encode("utf-8"))

def list_config(cli_config, tool_name):
    presets = get_dict(cli_config, "presets", "presets")
    mcps = get_dict(cli_config, "mcps", "mcps")
    tools = get_dict(cli_config, "tools", "tools")

    if tool_name is None:
        print("Tools:")
        for name, tool_cfg in tools.items():
            if isinstance(tool_cfg, dict):
                path_value = tool_cfg.get("path")
                format_value = tool_cfg.get("format")
                node_value = tool_cfg.get("config_node")
                if path_value:
                    print(f"  - {name}: {path_value} (format={format_value}, node={node_value})")
                else:
                    print(f"  - {name}: (unconfigured)")
            else:
                print(f"  - {name}: (unconfigured)")
        print("\nPresets:")
        for name, mcp_list in presets.items():
            if isinstance(mcp_list, list):
                print(f"  - {name}: {' '.join(mcp_list)}")
        print("\nDefined MCPs (from cli config):")
        if not mcps:
            print("  No MCPs found.")
            return
        for name, data in mcps.items():
            enabled = True
            if isinstance(data, dict):
                enabled = data.get("enabled", True)
            print(f"  - {name} (enabled: {str(enabled).lower()})")
        return

    if tool_name not in tools:
        print(f"Unknown tool: {tool_name}")
        sys.exit(1)

    print(f"Tool: {tool_name}")
    print("Presets:")
    for name, mcp_list in presets.items():
        if isinstance(mcp_list, list):
            print(f"  - {name}: {' '.join(mcp_list)}")
    print("\nDefined MCPs (from cli config):")
    if not mcps:
        print("  No MCPs found.")
        return
    for name, data in mcps.items():
        enabled = True
        if isinstance(data, dict):
            enabled = data.get("enabled", True)
        print(f"  - {name} (enabled: {str(enabled).lower()})")

def interactive_menu(stdscr, presets, mcp_states):
    curses.curs_set(0)
    preset_names = list(presets.keys())
    selected = [
        any(
            isinstance(mcp_states.get(mcp), dict) and mcp_states.get(mcp, {}).get("enabled", False)
            for mcp in presets[name]
        )
        for name in preset_names
    ]
    current_row = 0
    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, "MCP Manager", curses.A_BOLD)
        stdscr.addstr(1, 0, "Space: toggle | Enter: apply & start | q: quit")
        for i, name in enumerate(preset_names):
            box = "[x]" if selected[i] else "[ ]"
            mcp_list = ", ".join(presets[name])
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
        elif key in (10, 13):
            en = [preset_names[i] for i, val in enumerate(selected) if val]
            dis = [preset_names[i] for i, val in enumerate(selected) if not val]
            return en, dis
        elif key == ord('q'):
            return None, None

def parse_slice(slice_text):
    if ":" in slice_text:
        start_text, end_text = slice_text.split(":", 1)
        start = int(start_text) if start_text else None
        end = int(end_text) if end_text else None
        return slice(start, end)
    return int(slice_text)

def resolve_placeholder(token, mcp_name, mcp_def):
    if token == "name":
        return mcp_name
    if "[" in token and token.endswith("]"):
        base, bracket = token[:-1].split("[", 1)
        value = mcp_def.get(base)
        if value is None:
            return None
        if not isinstance(value, list):
            return None
        index = parse_slice(bracket)
        return value[index]
    return mcp_def.get(token)

def apply_template(template, mcp_name, mcp_def):
    if isinstance(template, dict):
        result = {}
        for key, value in template.items():
            rendered = apply_template(value, mcp_name, mcp_def)
            if rendered is None:
                continue
            result[key] = rendered
        return result
    if isinstance(template, list):
        items = []
        for value in template:
            rendered = apply_template(value, mcp_name, mcp_def)
            if rendered is None:
                continue
            items.append(rendered)
        return items
    if isinstance(template, str):
        if template.startswith("$"):
            return resolve_placeholder(template[1:], mcp_name, mcp_def)
        return template
    return copy.deepcopy(template)

def main():
    parser = argparse.ArgumentParser(description="MCP Manager")
    parser.add_argument("tool", nargs="?", help="Tool name (required unless --list)")
    parser.add_argument("-e", "--enable", nargs="+", metavar="PRESET", help="Enable presets")
    parser.add_argument("-d", "--disable", nargs="+", metavar="PRESET", help="Disable presets")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactive selection")
    parser.add_argument("-l", "--list", action="store_true", help="List status from cli config")
    parser.add_argument("-ns", "--no-start", action="store_true", help="Skip tool start")
    parser.add_argument("-s", "--show", action="store_true", help="Show MCP config for tool")
    parser.add_argument("--current", action="store_true", help="Show current MCP config for tool")
    parser.add_argument("-c", "--copy", action="store_true", help="Copy MCP config for tool to clipboard")

    args, _ = parser.parse_known_args()

    cli_config = load_cli_config()

    if args.list:
        list_config(cli_config, args.tool)
        return

    if not args.tool:
        print("Tool is required unless using --list.")
        sys.exit(1)

    argv = sys.argv[1:]
    passthrough = []
    if args.tool in argv:
        tool_index = argv.index(args.tool)
        passthrough = argv[tool_index + 1:]

    tool_cfg = get_tool_cfg(cli_config, args.tool)
    presets = get_dict(cli_config, "presets", "presets")
    mcps = get_dict(cli_config, "mcps", "mcps")
    template = get_tool_template(tool_cfg, args.tool)

    config = load_tool_config(tool_cfg)
    mcp_path = tool_cfg.get("config_node", "")
    mcp_node = get_node(config, mcp_path, create=True)
    if not isinstance(mcp_node, dict):
        print("MCP path does not point to an object.")
        sys.exit(1)

    to_enable = args.enable or []
    to_disable = args.disable or []

    if args.interactive:
        en, dis = curses.wrapper(interactive_menu, presets, mcp_node)
        if en is None:
            return
        to_enable, to_disable = en, dis

    updated = set()

    def ensure_mcp_entry(mcp_name):
        definition = mcps.get(mcp_name)
        if not isinstance(definition, dict):
            print(f"Missing MCP definition for '{mcp_name}' in {CLI_CONFIG_FILE}.")
            sys.exit(1)
        rendered = apply_template(template, mcp_name, definition)
        if not isinstance(rendered, dict):
            print(f"Template must render to an object for '{mcp_name}'.")
            sys.exit(1)
        return rendered

    def enable_mcp(mcp_name):
        if mcp_name in mcp_node and isinstance(mcp_node[mcp_name], dict):
            mcp_node[mcp_name]["enabled"] = True
        else:
            mcp_node[mcp_name] = ensure_mcp_entry(mcp_name)
            mcp_node[mcp_name]["enabled"] = True
        updated.add(mcp_name)

    def disable_mcp(mcp_name):
        if mcp_name in mcp_node and isinstance(mcp_node[mcp_name], dict):
            mcp_node[mcp_name]["enabled"] = False
            updated.add(mcp_name)

    def apply_state(names, state):
        for name in names:
            if name in presets:
                for mcp in presets[name]:
                    if state:
                        enable_mcp(mcp)
                    else:
                        disable_mcp(mcp)
            else:
                print(f"Warning: Preset '{name}' not found.")

    apply_state(to_enable, True)
    apply_state(to_disable, False)

    def render_mcps():
        rendered = {}
        for name in mcps.keys():
            rendered[name] = ensure_mcp_entry(name)
        return rendered

    def apply_state_to_rendered(rendered, names, state):
        for name in names:
            if name in presets:
                for mcp in presets[name]:
                    entry = rendered.get(mcp)
                    if entry is None:
                        entry = ensure_mcp_entry(mcp)
                        rendered[mcp] = entry
                    entry["enabled"] = state
            else:
                print(f"Warning: Preset '{name}' not found.")

    if args.current:
        fragment = build_fragment(mcp_path, mcp_node)
        output = format_output(tool_cfg, fragment)
        if args.show or not args.copy:
            print(output)
        if args.copy:
            copy_to_clipboard(output)
        return

    if args.show or args.copy:
        rendered = render_mcps()
        apply_state_to_rendered(rendered, to_enable, True)
        apply_state_to_rendered(rendered, to_disable, False)
        fragment = build_fragment(mcp_path, rendered)
        output = format_output(tool_cfg, fragment)
        if args.show:
            print(output)
        if args.copy:
            copy_to_clipboard(output)
        return

    if updated:
        save_tool_config(tool_cfg, config)

    if args.no_start:
        return

    command = tool_cfg.get("command")
    if isinstance(command, str):
        command = [command]
    if not isinstance(command, list) or not command:
        print("Tool command must be a non-empty list or string.")
        sys.exit(1)

    subprocess.run(command + passthrough)

if __name__ == "__main__":
    main()
