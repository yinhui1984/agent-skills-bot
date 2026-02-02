"""Logging helpers."""

from __future__ import annotations

import logging
from typing import Optional


def setup_textual_logger(log_widget) -> None:
    handler = TextualLogHandler(log_widget)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    logger = logging.getLogger("app.core")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def setup_cli_logger(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


class TextualLogHandler(logging.Handler):
    def __init__(self, widget) -> None:
        super().__init__()
        self.widget = widget

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.widget.write(msg)
