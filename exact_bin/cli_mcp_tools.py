#!/usr/bin/env python3

import sys


def _fail(message):
    print(message)
    sys.exit(1)


def _normalize_command_list(mcp_def, mcp_name):
    command = mcp_def.get("command")
    if not isinstance(command, list) or not command:
        _fail(f"Invalid or missing command for '{mcp_name}'.")
    return command


def _normalize_environment(mcp_def, mcp_name):
    env = mcp_def.get("environment")
    if env is None:
        return None
    if not isinstance(env, dict):
        _fail(f"Invalid environment for '{mcp_name}'.")
    return env


class BaseTransformer:
    state_field = "enabled"
    state_means_enabled = True

    def transform_entry(self, mcp_name, mcp_def, enabled):
        raise NotImplementedError


def _normalize_headers(mcp_def, mcp_name):
    headers = mcp_def.get("headers")
    if headers is None:
        return None
    if not isinstance(headers, dict):
        _fail(f"Invalid headers for '{mcp_name}'.")
    return headers


def _normalize_disabled_tools(mcp_def, mcp_name):
    disabled_tools = mcp_def.get("disabled_tools")
    if disabled_tools is None:
        return None
    if not isinstance(disabled_tools, list) or not all(
        isinstance(item, str) for item in disabled_tools
    ):
        _fail(f"Invalid disabled_tools for '{mcp_name}'.")
    return disabled_tools


def _normalize_timeout(mcp_def, mcp_name):
    timeout = mcp_def.get("timeout")
    if timeout is None:
        return None
    if not isinstance(timeout, (int, float)):
        _fail(f"Invalid timeout for '{mcp_name}'.")
    return timeout


def _copy_optional_fields(entry, mcp_def, mcp_name, fields):
    for key, normalizer in fields.items():
        if key not in mcp_def:
            continue
        if normalizer is not None:
            value = normalizer(mcp_def, mcp_name)
        else:
            value = mcp_def.get(key)
        if value is None:
            continue
        entry[key] = value


def make_transformer(
    *,
    command_key,
    args_key,
    env_key,
    type_key=None,
    type_from_mcp=False,
    local_type=None,
    remote_type=None,
    state_field="enabled",
    state_means_enabled=True,
    command_mode="first",
    extra_fields=None,
):
    class _T(BaseTransformer):
        def transform_entry(self, mcp_name, mcp_def, enabled):
            entry = {}
            mcp_type = mcp_def.get("type")

            if mcp_type == "local":
                command = _normalize_command_list(mcp_def, mcp_name)
                if command_mode == "first":
                    entry[command_key] = command[0]
                elif command_mode == "list":
                    entry[command_key] = command
                else:
                    _fail(f"Invalid command_mode: {command_mode}")
                if args_key:
                    entry[args_key] = command[1:]
                if type_key:
                    if type_from_mcp:
                        entry[type_key] = mcp_type
                    elif local_type is not None:
                        entry[type_key] = local_type
            elif mcp_type == "remote":
                url = mcp_def.get("url")
                if not url:
                    _fail(f"Missing url for '{mcp_name}'.")
                entry["url"] = url
                if type_key:
                    if type_from_mcp:
                        entry[type_key] = mcp_type
                    elif remote_type is not None:
                        entry[type_key] = remote_type(mcp_def) if callable(remote_type) else remote_type
            else:
                _fail(f"Invalid type for '{mcp_name}'.")

            env = _normalize_environment(mcp_def, mcp_name)
            if env and env_key:
                entry[env_key] = env

            if extra_fields:
                _copy_optional_fields(entry, mcp_def, mcp_name, extra_fields)

            if state_field is not None and enabled is not None:
                entry[state_field] = (
                    bool(enabled) if state_means_enabled else not bool(enabled)
                )

            return entry

    _T.state_field = state_field
    _T.state_means_enabled = state_means_enabled
    return _T()


def _crush_remote_type(mcp_def):
    transport = mcp_def.get("transport", "http")
    if transport not in ("http", "sse"):
        _fail(f"Invalid transport for Crush: {transport}")
    return transport


TOOLS = {
    "opencode": {
        "format": "json",
        "path": "~/.config/opencode/opencode.json",
        "config_node": "mcp",
        "command": ["opencode"],
        "transformer": make_transformer(
            command_key="command",
            args_key=None,
            env_key="environment",
            type_key="type",
            type_from_mcp=True,
            command_mode="list",
        ),
    },
    "codex": {
        "format": "toml",
        "path": "~/.codex/config.toml",
        "config_node": "mcp_servers",
        "command": ["codex"],
        "transformer": make_transformer(
            command_key="command",
            args_key="args",
            env_key="env",
            command_mode="first",
        ),
    },
    "gemini": {
        "format": "json",
        "path": "~/Projects/Personal/cli-mcp/examples/settings.json",
        "config_node": "mcpServers",
        "command": ["gemini"],
        "transformer": make_transformer(
            command_key="command",
            args_key="args",
            env_key="env",
            command_mode="first",
            state_field=None,
        ),
    },
    "crush": {
        "format": "json",
        "path": "~/.config/crush/crush.json",
        "config_node": "mcp",
        "command": ["crush"],
        "transformer": make_transformer(
            command_key="command",
            args_key="args",
            env_key="env",
            type_key="type",
            local_type="stdio",
            remote_type=_crush_remote_type,
            state_field="disabled",
            state_means_enabled=False,
            command_mode="first",
            extra_fields={
                "timeout": _normalize_timeout,
                "disabled_tools": _normalize_disabled_tools,
                "headers": _normalize_headers,
            },
        ),
    },
}


def get_tools():
    return TOOLS


def get_transformer(tool_name):
    tool_cfg = TOOLS.get(tool_name)
    if tool_cfg is None:
        _fail(f"No tool configured for '{tool_name}'.")
    transformer = tool_cfg.get("transformer")
    if transformer is None:
        _fail(f"No transformer configured for tool '{tool_name}'.")
    return transformer
