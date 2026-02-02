"""Top-level CLI loop and notification pump."""

from __future__ import annotations

import json
import os
import threading
import time

from rich.text import Text

from agent_skills_bot.interfaces.cli_app import run_cli
from agent_skills_bot.interfaces.cli_theme import (
    INFO_RULE_STYLE,
    WARNING_RULE_STYLE,
    console,
    _render_rule,
)
from agent_skills_bot.interfaces.cli_ui import _handle_command, _prompt_query, _render_banner
from agent_skills_bot.utils.bootstrap import ensure_default_user_config
from agent_skills_bot.utils.logger import setup_cli_logger
from agent_skills_bot.utils.mcp_client import drain_mcp_notifications


NOTIFY_POLL_SECONDS = 1.0


def run_cli_loop(
    initial_query: str | None,
    loop: bool = True,
    tool_loop: bool = True,
    max_loop_count: int = 10,
) -> None:
    setup_cli_logger()
    ensure_default_user_config()
    if initial_query is None:
        _render_banner()
    session_state: dict[str, object] = {
        "cwd": os.getcwd(),
        "created": set(),
        "modified": set(),
        "last_command": "",
        "last_paths": [],
        "last_abs_path": "",
        "artifacts": {},
    }
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
                pending = _prompt_query()
            if not pending:
                break
            if pending.startswith("/"):
                handled = _handle_command(pending)
                if not handled:
                    _render_rule("Command", style=WARNING_RULE_STYLE)
                    console.print("Unknown command. Try /help")
                pending = None
                if not loop:
                    break
                continue
            run_cli(
                pending,
                tool_loop=tool_loop,
                max_loop_count=max_loop_count,
                session_state=session_state,
            )
            console.print()
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
            _render_rule("MCP Notifications", style=INFO_RULE_STYLE)
            rendered = Text()
            for server, items in notes.items():
                rendered.append(f"{server}\n", style="bold")
                for item in items:
                    rendered.append(f"  {json.dumps(item, ensure_ascii=False)}\n", style="dim")
            console.print(rendered)
        time.sleep(NOTIFY_POLL_SECONDS)
