"""CLI entrypoints for agent-skills-bot."""

from __future__ import annotations

from agent_skills_bot.interfaces.cli_app import run_cli
from agent_skills_bot.interfaces.cli_loop import run_cli_loop

__all__ = ["run_cli", "run_cli_loop"]
