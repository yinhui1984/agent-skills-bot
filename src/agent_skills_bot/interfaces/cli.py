"""CLI for agent-skills-bot."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

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


def run_cli(user_input: str) -> None:
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
        command = build_command(skill_query.skill, skill_query.query, reference_texts)
    except Exception as exc:
        logger.error(str(exc))
        console.print(Rule("Error", style="red"))
        console.print(str(exc))
        console.print(Rule(style="red"))
        return

    command_text = " ".join(command)
    allowed_tools = allowed_tools_for(get_skill_meta(skill_query.skill))
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
                    args = _repair_mcp_args(user_input, server, tool, raw, schema)
            else:
                tools = list_mcp_tools().get(server, [])
                schema = None
                for item in tools:
                    if item.get("name") == tool:
                        schema = item.get("inputSchema")
                        break
                args = _infer_mcp_args(user_input, server, tool, schema)
                console.print(Rule("MCP Args", style="cyan"))
                console.print(json.dumps(args, indent=2, ensure_ascii=False))
                console.print(Rule(style="cyan"))
            result = call_mcp_tool(server, tool, args)
            output = json.dumps(result, indent=2, ensure_ascii=False)
            _render_output(output.splitlines())
        else:
            result = asyncio.run(execute_command(skill_query.skill, command))
            _render_output(result.lines)
    except Exception as exc:
        logger.error(str(exc))
        console.print(Rule("Error", style="red"))
        console.print(str(exc))
        console.print(Rule(style="red"))
        return


def _infer_mcp_args(
    user_input: str, server: str, tool: str, schema: dict | None
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
    ]
    response = chat_completion(messages, response_format={"type": "json_object"})
    try:
        content = response["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Failed to infer MCP arguments") from exc


def _get_mcp_schema(server: str, tool: str) -> dict | None:
    tools = list_mcp_tools().get(server, [])
    for item in tools:
        if item.get("name") == tool:
            return item.get("inputSchema")
    return None


def _repair_mcp_args(
    user_input: str, server: str, tool: str, raw: str, schema: dict | None
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
    ]
    response = chat_completion(messages, response_format={"type": "json_object"})
    try:
        content = response["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Failed to repair MCP arguments") from exc


def run_cli_loop(initial_query: str | None, loop: bool = True) -> None:
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
            run_cli(pending)
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
