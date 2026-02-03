"""Logging helpers."""

from __future__ import annotations

import logging
from typing import Optional


class _SuppressAiLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not (msg.startswith("AI request ") or msg.startswith("AI response "))


def setup_textual_logger(log_widget) -> None:
    handler = TextualLogHandler(log_widget)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    logger = logging.getLogger("app.core")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def setup_cli_logger(level: int = logging.INFO, *, suppress_ai_logs: bool = False) -> None:
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")
    if suppress_ai_logs:
        root = logging.getLogger()
        for handler in root.handlers:
            handler.addFilter(_SuppressAiLogFilter())


class TextualLogHandler(logging.Handler):
    def __init__(self, widget) -> None:
        super().__init__()
        self.widget = widget

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.widget.write(msg)
