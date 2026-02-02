"""CLI UI helpers for agent-skills-bot."""

from __future__ import annotations

import json
from pathlib import Path

from prompt_toolkit import Application
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, ConditionalContainer
from prompt_toolkit.filters import Condition
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.widgets import Frame, TextArea, Label
from rich.text import Text

from agent_skills_bot.core.models import SkillPlan
from agent_skills_bot.core.skills import load_skills
from agent_skills_bot.interfaces.cli_theme import (
    INFO_RULE_STYLE,
    RESULT_RULE_STYLE,
    console,
    _render_rule,
)
from agent_skills_bot.utils.mcp_client import (
    drain_mcp_notifications,
    list_mcp_servers,
    list_mcp_tools_summary,
)
_QUERY_HISTORY = InMemoryHistory()

COMMANDS = {
    "/list": "List all installed skills",
    "/help": "Show available commands",
    "/mcp": "List MCP servers and tools",
    "/mcp-notifications": "Show pending MCP notifications",
    "/quit": "Exit the CLI",
}


class _CommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for cmd in COMMANDS:
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text))


def _prompt_query() -> str:
    text_area = TextArea(
        multiline=False,
        prompt="\u203a ",
        completer=_CommandCompleter(),
        complete_while_typing=True,
        history=_QUERY_HISTORY,
    )
    hint_text = "Type a query or use / for commands"
    hint = Label(hint_text, style="class:hint")
    show_hint = Condition(lambda: not text_area.text.strip())
    frame = Frame(
        HSplit(
            [
                text_area,
                ConditionalContainer(hint, filter=show_hint),
            ]
        )
    )
    style = PTStyle.from_dict(
        {
            "frame": "bg:#2b2b2b",
            "frame.border": "#666666",
            "text-area": "bg:#2b2b2b",
            "text-area.prompt": "bold",
            "hint": "#888888 bg:#2b2b2b",
        }
    )
    bindings = KeyBindings()

    @bindings.add("enter")
    def _accept(event) -> None:
        value = text_area.text.strip()
        if value:
            _QUERY_HISTORY.append_string(value)
        event.app.exit(result=value)

    @bindings.add("c-c")
    def _cancel(event) -> None:
        event.app.exit(result="")

    app = Application(
        layout=Layout(HSplit([frame])),
        key_bindings=bindings,
        style=style,
        full_screen=False,
    )
    return app.run()


def _render_output(lines: list[str]) -> None:
    if not lines:
        _render_rule("Result", style=RESULT_RULE_STYLE)
        console.print("(no output)")
        return

    rendered = Text("", no_wrap=False)
    for line in lines:
        if line.startswith("\u2514 "):
            rendered.append(line + "\n", style="dim")
        elif line.strip() == "":
            rendered.append("\n")
        else:
            rendered.append(line + "\n")

    _render_rule("Result", style=RESULT_RULE_STYLE)
    console.print(rendered)


def _render_command_help() -> None:
    rendered = Text()
    for cmd, desc in COMMANDS.items():
        rendered.append(f"{cmd}\n", style="bold")
        rendered.append(f"  {desc}\n")
    _render_rule("Commands", style=INFO_RULE_STYLE)
    console.print(rendered)


def _render_banner() -> None:
    banner = (
        " ____    _  __  ___   _       _           ____     ___    _____ \n"
        "/ ___|  | |/ / |_ _| | |     | |         | __ )   / _ \\  |_   _|\n"
        "\\___ \\  | ' /   | |  | |     | |         |  _ \\  | | | |   | |  \n"
        " ___) | | . \\   | |  | |___  | |___      | |_) | | |_| |   | |  \n"
        "|____/  |_|\\_\\ |___| |_____| |_____|     |____/   \\___/    |_|  \n"
    )
    console.print(banner, style="bold cyan")
    config_dir = Path.home() / ".agent-skills-bot"
    console.print(f"Config dir: {config_dir}", style="dim")
    console.print("  - skills/: installed skills (SKILL.md)", style="dim")
    console.print(
        "  - command-allowlist.json: allowlisted shell commands for run_command",
        style="dim",
    )
    console.print("  - mcp.json: MCP server configuration", style="dim")


def _render_plan(plan: SkillPlan) -> None:
    _render_rule("Plan", style=INFO_RULE_STYLE)
    for idx, step in enumerate(plan.steps, 1):
        requires = ", ".join(step.requires or []) if step.requires else "(none)"
        notes = step.notes or ""
        console.print(f"{idx}. {step.skill}")
        console.print(f"   input: {step.input}")
        console.print(f"   requires: {requires}")
        if notes:
            console.print(f"   notes: {notes}")


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
            _render_rule("Skills", style=INFO_RULE_STYLE)
            console.print("(no skills found)")
            return True
        rendered = Text()
        for skill in skills:
            rendered.append(f"{skill.name}\n", style="bold")
            rendered.append(f"  {skill.description}\n")
            rendered.append(f"  {skill.path}\n\n", style="dim")
        _render_rule("Skills", style=INFO_RULE_STYLE)
        console.print(rendered)
        return True
    if command == "/mcp":
        servers = list_mcp_servers()
        _render_rule("MCP", style=INFO_RULE_STYLE)
        if not servers:
            console.print("(no MCP servers configured)")
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
        return True
    if command == "/mcp-notifications":
        notes = drain_mcp_notifications()
        _render_rule("MCP Notifications", style=INFO_RULE_STYLE)
        if not notes:
            console.print("(no notifications)")
            return True
        rendered = Text()
        for server, items in notes.items():
            rendered.append(f"{server}\n", style="bold")
            for item in items:
                rendered.append(f"  {json.dumps(item, ensure_ascii=False)}\n", style="dim")
        console.print(rendered)
        return True
    if command in {"/quit", "/exit"}:
        raise SystemExit(0)
    return False
