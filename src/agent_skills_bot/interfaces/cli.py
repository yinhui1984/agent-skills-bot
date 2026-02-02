"""CLI for agent-skills-bot."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import threading
import time
from datetime import datetime, timezone

from rich.console import Console
from rich.rule import Rule
from rich.text import Text

from agent_skills_bot.core.router import route_skill
from agent_skills_bot.core.skill_runner import (
    allowed_tools_for,
    build_command,
    execute_command,
    get_skill_meta,
    list_reference_files,
    read_reference_files,
)
from agent_skills_bot.core.skills import load_skills
from agent_skills_bot.utils.logger import setup_cli_logger
from agent_skills_bot.utils.mcp_client import (
    call_mcp_tool,
    drain_mcp_notifications,
    list_mcp_servers,
    list_mcp_tools_summary,
    list_mcp_tools,
)
from agent_skills_bot.utils.deepseek_client import chat_completion


console = Console()
NOTIFY_POLL_SECONDS = 1.0

COMMANDS = {
    "/list": "List all installed skills",
    "/help": "Show available commands",
    "/mcp": "List MCP servers and tools",
    "/mcp-notifications": "Show pending MCP notifications",
    "/quit": "Exit the CLI",
}


def _render_output(lines: list[str]) -> None:
    if not lines:
        console.print(Rule("Result", style="green"))
        console.print("(no output)")
        console.print(Rule(style="green"))
        return

    rendered = Text("", no_wrap=False)
    for line in lines:
        if line.startswith("└ "):
            rendered.append(line + "\n", style="dim")
        elif line.strip() == "":
            rendered.append("\n")
        else:
            rendered.append(line + "\n")

    console.print(Rule("Result", style="green"))
    console.print(rendered)
    console.print(Rule(style="green"))


def _render_command_help() -> None:
    rendered = Text()
    for cmd, desc in COMMANDS.items():
        rendered.append(f"{cmd}\n", style="bold")
        rendered.append(f"  {desc}\n")
    console.print(Rule("Commands", style="blue"))
    console.print(rendered)
    console.print(Rule(style="blue"))


def _handle_command(command: str) -> bool:
    if command == "/":
        _render_command_help()
        return True
    if command == "/help":
        _render_command_help()
        return True
    if command == "/list":
        skills = load_skills()
        if not skills:
            console.print(Rule("Skills", style="yellow"))
            console.print("(no skills found)")
            console.print(Rule(style="yellow"))
            return True
        rendered = Text()
        for skill in skills:
            rendered.append(f"{skill.name}\n", style="bold")
            rendered.append(f"  {skill.description}\n")
            rendered.append(f"  {skill.path}\n\n", style="dim")
        console.print(Rule("Skills", style="green"))
        console.print(rendered)
        console.print(Rule(style="green"))
        return True
    if command == "/mcp":
        servers = list_mcp_servers()
        console.print(Rule("MCP", style="blue"))
        if not servers:
            console.print("(no MCP servers configured)")
            console.print(Rule(style="blue"))
            return True
        console.print(
            "Note: first-time MCP startup may take time to install/load dependencies. Please wait..."
        )
        summary = list_mcp_tools_summary()
        rendered = Text()
        for server in servers:
            rendered.append(f"{server}\n", style="bold")
            tools = summary.get(server, [])
            if tools:
                rendered.append(f"  {', '.join(tools)}\n")
            else:
                rendered.append("  (no tools)\n", style="dim")
        console.print(rendered)
        console.print(Rule(style="blue"))
        return True
    if command == "/mcp-notifications":
        notes = drain_mcp_notifications()
        console.print(Rule("MCP Notifications", style="blue"))
        if not notes:
            console.print("(no notifications)")
            console.print(Rule(style="blue"))
            return True
        rendered = Text()
        for server, items in notes.items():
            rendered.append(f"{server}\n", style="bold")
            for item in items:
                rendered.append(f"  {json.dumps(item, ensure_ascii=False)}\n", style="dim")
        console.print(rendered)
        console.print(Rule(style="blue"))
        return True
    if command in {"/quit", "/exit"}:
        raise SystemExit(0)
    return False


def run_cli(user_input: str, tool_loop: bool = True, max_loop_count: int = 10) -> None:
    setup_cli_logger()
    logger = logging.getLogger("app.core")

    console.print(Rule("Input", style="blue"))
    console.print(user_input)
    console.print(Rule(style="blue"))
    console.print("Running...", style="yellow")

    try:
        skill_query = route_skill(user_input)
        references = list_reference_files(skill_query.skill)
        reference_texts = []
        if references:
            console.print(Rule("References", style="cyan"))
            console.print("\n".join(references))
            console.print(Rule(style="cyan"))
            load_refs = console.input("Load references into context? (Y/n): ").strip().lower()
            if not load_refs or load_refs in {"y", "yes"}:
                reference_texts = read_reference_files(references)
    except Exception as exc:
        logger.error(str(exc))
        console.print(Rule("Error", style="red"))
        console.print(str(exc))
        console.print(Rule(style="red"))
        return

    _run_tool_loop(
        skill_query.skill,
        skill_query.query,
        user_input,
        reference_texts,
        tool_loop=tool_loop,
        max_loop_count=max_loop_count,
    )


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
    response = chat_completion(messages, response_format={"type": "json_object"})
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
    response = chat_completion(messages, response_format={"type": "json_object"})
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


def _run_tool_loop(
    skill_name: str,
    query: str,
    user_input: str,
    reference_texts: list[str],
    tool_loop: bool,
    max_loop_count: int,
) -> None:
    logger = logging.getLogger("app.core")
    messages = [
        {
            "role": "system",
            "content": "You are executing a tool loop. Use the environment context provided.",
        },
        {"role": "user", "content": _environment_context()},
        {"role": "user", "content": f"User: {user_input}"},
    ]
    step = 0
    current_query = query
    last_pid: int | None = None
    while True:
        step += 1
        if step > max_loop_count:
            console.print(Rule("Warning", style="yellow"))
            console.print("Max loop count reached.")
            console.print(Rule(style="yellow"))
            return
        command = build_command(skill_name, current_query, reference_texts)
        command_text = " ".join(command)
        allowed_tools = allowed_tools_for(get_skill_meta(skill_name))
        if allowed_tools:
            console.print(Rule("allowed-tools", style="cyan"))
            console.print(", ".join(allowed_tools))
            console.print(Rule(style="cyan"))
            if command and command[0] not in allowed_tools:
                console.print(Rule("Blocked", style="red"))
                console.print(f"Command tool '{command[0]}' is not in allowed-tools.")
                console.print(Rule(style="red"))
                return
        console.print(Rule("Command", style="magenta"))
        console.print(command_text)
        console.print(Rule(style="magenta"))
        confirm = console.input("[bold yellow]Execute command?[/bold yellow] (Y/n): ").strip().lower()
        if confirm and confirm not in {"y", "yes"}:
            console.print("Cancelled.", style="dim")
            return

        try:
            if command and command[0].startswith("mcp__"):
                tool_spec = command[0].split("__", 2)
                if len(tool_spec) != 3:
                    raise RuntimeError("Invalid MCP tool format. Use mcp__server__tool.")
                server = tool_spec[1]
                tool = tool_spec[2]
                args = {}
                if len(command) > 1:
                    raw = " ".join(command[1:])
                    try:
                        args = json.loads(raw)
                    except json.JSONDecodeError:
                        schema = _get_mcp_schema(server, tool)
                        args = _repair_mcp_args(user_input, server, tool, raw, schema, messages)
                else:
                    tools = list_mcp_tools().get(server, [])
                    schema = None
                    for item in tools:
                        if item.get("name") == tool:
                            schema = item.get("inputSchema")
                            break
                    args = _infer_mcp_args(user_input, server, tool, schema, messages)
                args = _normalize_mcp_args(args)
                if tool == "read_process_output":
                    pid = args.get("pid")
                    if not pid and last_pid:
                        args["pid"] = last_pid
                console.print(Rule("MCP Args", style="cyan"))
                console.print(json.dumps(args, indent=2, ensure_ascii=False))
                console.print(Rule(style="cyan"))
                result = call_mcp_tool(server, tool, args)
                output = json.dumps(result, indent=2, ensure_ascii=False)
                _render_output(output.splitlines())
                tool_output = output
            else:
                result = asyncio.run(execute_command(skill_name, command))
                _render_output(result.lines)
                tool_output = result.raw_output
        except Exception as exc:
            logger.error(str(exc))
            console.print(Rule("Error", style="red"))
            console.print(str(exc))
            console.print(Rule(style="red"))
            return

        if command and command[0].startswith("mcp__"):
            pid_match = re.search(r"PID\\s+(\\d+)", tool_output)
            if pid_match:
                last_pid = int(pid_match.group(1))

        if not tool_loop:
            return

        messages.append({"role": "assistant", "content": f"Command: {command_text}"})
        messages.append({"role": "user", "content": f"Tool output:\n{tool_output}"})
        decision = _decide_next_step(messages, user_input)
        if decision.get("done"):
            console.print(Rule("Result", style="green"))
            console.print(decision.get("summary", "Done."))
            console.print(Rule(style="green"))
            return
        current_query = decision.get("next_input", "")
        if not current_query:
            console.print(Rule("Warning", style="yellow"))
            console.print("No next step provided; stopping.")
            console.print(Rule(style="yellow"))
            return


def _decide_next_step(messages: list[dict[str, str]], user_input: str) -> dict:
    system = (
        "Return json only. Decide whether the task is complete. "
        "Schema: {\"done\": true|false, \"summary\": \"...\", \"next_input\": \"...\"}."
    )
    response = chat_completion(
        [{"role": "system", "content": system}, *messages],
        response_format={"type": "json_object"},
    )
    try:
        content = response["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return _repair_decision(messages, user_input)


def _repair_decision(messages: list[dict[str, str]], user_input: str) -> dict:
    system = (
        "Return json only. Repair the decision into valid JSON. "
        "Schema: {\"done\": true|false, \"summary\": \"...\", \"next_input\": \"...\"}."
    )
    response = chat_completion(
        [{"role": "system", "content": system}, *messages, {"role": "user", "content": f"User: {user_input}"}],
        response_format={"type": "json_object"},
    )
    try:
        content = response["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return {
            "done": True,
            "summary": "No further steps inferred; see tool output above.",
            "next_input": "",
        }


def _environment_context() -> str:
    shell = os.environ.get("SHELL", "(unknown)")
    now = datetime.now(timezone.utc).isoformat()
    os_info = platform.platform()
    return f"Environment: os={os_info}; shell={shell}; time_utc={now}"


def run_cli_loop(
    initial_query: str | None,
    loop: bool = True,
    tool_loop: bool = True,
    max_loop_count: int = 10,
) -> None:
    setup_cli_logger()
    stop_event = threading.Event()
    notify_thread = threading.Thread(
        target=_notification_loop,
        args=(stop_event,),
        daemon=True,
    )
    notify_thread.start()
    pending = initial_query
    try:
        while True:
            if not pending:
                pending = console.input("[bold]Query[/bold] (empty to quit): ").strip()
            if not pending:
                break
            if pending.startswith("/"):
                handled = _handle_command(pending)
                if not handled:
                    console.print(Rule("Command", style="yellow"))
                    console.print("Unknown command. Try /help")
                    console.print(Rule(style="yellow"))
                pending = None
                if not loop:
                    break
                continue
            run_cli(pending, tool_loop=tool_loop, max_loop_count=max_loop_count)
            pending = None
            if not loop:
                break
    except KeyboardInterrupt:
        console.print("\nBye.", style="dim")
    finally:
        stop_event.set()


def _notification_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        notes = drain_mcp_notifications()
        if notes:
            console.print(Rule("MCP Notifications", style="blue"))
            rendered = Text()
            for server, items in notes.items():
                rendered.append(f"{server}\n", style="bold")
                for item in items:
                    rendered.append(f"  {json.dumps(item, ensure_ascii=False)}\n", style="dim")
            console.print(rendered)
            console.print(Rule(style="blue"))
        time.sleep(NOTIFY_POLL_SECONDS)
