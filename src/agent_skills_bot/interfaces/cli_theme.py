"""Shared CLI rendering helpers and styles."""

from __future__ import annotations

from rich.console import Console
from rich.text import Text


console = Console()

RULE_CHAR = "\u2500"
INFO_RULE_STYLE = "grey50"
RESULT_RULE_STYLE = INFO_RULE_STYLE
ERROR_RULE_STYLE = "red"
WARNING_RULE_STYLE = "yellow"


def _render_rule(title: str, style: str) -> None:
    width = console.size.width if console else 80
    if width <= 0:
        width = 80
    label = f"{RULE_CHAR} {title} " if title else RULE_CHAR
    if len(label) >= width:
        console.print(Text(label[:width], style=style))
        return
    line = f"{label}{RULE_CHAR * (width - len(label))}"
    console.print(Text(line, style=style))
