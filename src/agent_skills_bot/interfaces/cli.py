"""CLI for agent-skills-bot."""

from __future__ import annotations

import asyncio
import logging

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


console = Console()

COMMANDS = {
    "/list": "List all installed skills",
    "/help": "Show available commands",
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
            load_refs = console.input("Load references into context? (y/N): ").strip().lower()
            if load_refs in {"y", "yes"}:
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
        result = asyncio.run(execute_command(skill_query.skill, command))
    except Exception as exc:
        logger.error(str(exc))
        console.print(Rule("Error", style="red"))
        console.print(str(exc))
        console.print(Rule(style="red"))
        return

    _render_output(result.lines)


def run_cli_loop(initial_query: str | None, loop: bool = True) -> None:
    setup_cli_logger()
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
