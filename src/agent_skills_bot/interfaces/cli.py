"""CLI for agent-skills-bot."""

from __future__ import annotations

import asyncio
import logging

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from agent_skills_bot.core.router import route_skill
from agent_skills_bot.core.skill_runner import build_command, execute_command
from agent_skills_bot.utils.logger import setup_cli_logger


console = Console()


def _render_output(lines: list[str]) -> None:
    if not lines:
        console.print(Panel("(no output)", title="Result", border_style="green"))
        return

    rendered = Text("", no_wrap=False)
    for line in lines:
        if line.startswith("└ "):
            rendered.append(line + "\n", style="dim")
        elif line.strip() == "":
            rendered.append("\n")
        else:
            rendered.append(line + "\n")

    console.print(Panel(rendered, title="Result", border_style="green"))


def run_cli(user_input: str) -> None:
    setup_cli_logger()
    logger = logging.getLogger("app.core")

    console.print(Panel(user_input, title="Input", border_style="blue"))
    console.print("Running...", style="yellow")

    try:
        skill_query = route_skill(user_input)
        command = build_command(skill_query.skill, skill_query.query)
    except Exception as exc:
        logger.error(str(exc))
        console.print(Panel(str(exc), title="Error", border_style="red"))
        return

    command_text = " ".join(command)
    console.print(Panel(command_text, title="Command", border_style="magenta"))
    confirm = console.input("[bold yellow]Execute command?[/bold yellow] (Y/n): ").strip().lower()
    if confirm and confirm not in {"y", "yes"}:
        console.print("Cancelled.", style="dim")
        return

    try:
        result = asyncio.run(execute_command(skill_query.skill, command))
    except Exception as exc:
        logger.error(str(exc))
        console.print(Panel(str(exc), title="Error", border_style="red"))
        return

    _render_output(result.lines)


def run_cli_loop(initial_query: str | None, loop: bool = True) -> None:
    setup_cli_logger()
    pending = initial_query
    while True:
        if not pending:
            pending = console.input("[bold]Query[/bold] (empty to quit): ").strip()
        if not pending:
            break
        run_cli(pending)
        pending = None
        if not loop:
            break
