"""Logging helpers."""

from __future__ import annotations

import logging
from typing import Optional


_live_animation_active = False


def set_live_animation(active: bool) -> None:
    global _live_animation_active
    _live_animation_active = active


class _SuppressAiLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage().lstrip()
        return not (msg.startswith("AI request ") or msg.startswith("AI response "))


class _LiveAnimationNewlineFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not _live_animation_active:
            return True
        msg = record.getMessage()
        if msg.startswith("\r\x1b[2K"):
            return True
        record.msg = f"\r\x1b[2K{msg}"
        record.args = ()
        return True


def setup_textual_logger(log_widget) -> None:
    handler = TextualLogHandler(log_widget)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    logger = logging.getLogger("app.core")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def setup_cli_logger(level: int = logging.INFO, *, suppress_ai_logs: bool = False) -> None:
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")
    root = logging.getLogger()
    for handler in root.handlers:
        if suppress_ai_logs:
            handler.addFilter(_SuppressAiLogFilter())
        handler.addFilter(_LiveAnimationNewlineFilter())


class TextualLogHandler(logging.Handler):
    def __init__(self, widget) -> None:
        super().__init__()
        self.widget = widget

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.widget.write(msg)
