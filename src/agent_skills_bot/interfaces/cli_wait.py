"""Shared wait animation for interactive CLI."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

from rich.live import Live
from rich.text import Text


FRAMES = [
    "(o     )",
    "( o    )",
    "(  o   )",
    "(   o  )",
    "(    o )",
    "(     o)",
    "(    o )",
    "(   o  )",
    "(  o   )",
    "( o    )",
]
FRAME_DELAY = 0.12  # seconds
GRADIENT = [
    "pale_green1",
    "light_green",
    "green3",
    "green4",
    "dark_green",
]


@contextmanager
def wait_animation(message: str, *, console, enabled: bool = True):
    if not enabled:
        yield
        return
    stop_event = threading.Event()

    def _run(live: Live) -> None:
        idx = 0
        while not stop_event.is_set():
            frame = FRAMES[idx % len(FRAMES)]
            color = GRADIENT[idx % len(GRADIENT)]
            live.update(Text(f"{frame} {message}", style=color))
            idx += 1
            time.sleep(FRAME_DELAY)

    with Live(Text(""), console=console, refresh_per_second=30, transient=True) as live:
        thread = threading.Thread(target=_run, args=(live,), daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop_event.set()
            thread.join(timeout=1)
