"""MCP argument handling for the CLI tool loop."""

from __future__ import annotations

import json

from agent_skills_bot.interfaces.cli_state import _strip_quotes
from agent_skills_bot.utils.deepseek_client import chat_completion
from agent_skills_bot.utils.mcp_client import list_mcp_tools


def _infer_mcp_args(
    user_input: str,
    server: str,
    tool: str,
    schema: dict | None,
    context: list[dict[str, str]],
) -> dict:
    system = (
        "You must output JSON only. Infer MCP tool arguments from the user request. "
        "Use the provided input schema if available. Do not include extra keys."
    )
    schema_text = json.dumps(schema, ensure_ascii=False) if schema else "(none)"
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"Tool: {server}.{tool}\nSchema: {schema_text}\nUser: {user_input}",
        },
        *context,
    ]
    response = chat_completion(
        messages,
        response_format={"type": "json_object"},
        purpose="infer_mcp_args",
    )
    try:
        content = response["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raw = response["choices"][0]["message"]["content"]
        return _repair_mcp_args(user_input, server, tool, raw, schema, context)


def _get_mcp_schema(server: str, tool: str) -> dict | None:
    tools = list_mcp_tools().get(server, [])
    for item in tools:
        if item.get("name") == tool:
            return item.get("inputSchema")
    return None


def _repair_mcp_args(
    user_input: str,
    server: str,
    tool: str,
    raw: str,
    schema: dict | None,
    context: list[dict[str, str]],
) -> dict:
    system = (
        "Return JSON only. Repair the MCP arguments into a valid JSON object. "
        "Do not execute or expand shell expressions; keep them as plain strings. "
        "Use the input schema if available and do not add extra keys."
    )
    schema_text = json.dumps(schema, ensure_ascii=False) if schema else "(none)"
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"Tool: {server}.{tool}\nSchema: {schema_text}\nRaw: {raw}\nUser: {user_input}",
        },
        *context,
    ]
    response = chat_completion(
        messages,
        response_format={"type": "json_object"},
        purpose="repair_mcp_args",
    )
    try:
        content = response["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Failed to repair MCP arguments") from exc


def _normalize_mcp_args(args: dict) -> dict:
    if "arguments" in args and isinstance(args["arguments"], dict):
        return args["arguments"]
    if "args" in args and isinstance(args["args"], dict):
        return args["args"]
    if "command" in args and isinstance(args["command"], str) and args["command"].startswith("mcp__"):
        return {}
    return args


def _coerce_mcp_args(raw: str, tool: str) -> dict | None:
    raw = raw.strip()
    if not raw:
        return None
    if tool == "run_command":
        if raw.startswith("{") and raw.endswith("}"):
            inner = raw[1:-1].strip()
            if inner.startswith("command:"):
                cmd = inner[len("command:") :].strip()
                return {"command": _strip_quotes(cmd)}
        if raw.startswith("command:"):
            cmd = raw[len("command:") :].strip()
            return {"command": _strip_quotes(cmd)}
        if not raw.startswith("{"):
            return {"command": raw}
    return None
