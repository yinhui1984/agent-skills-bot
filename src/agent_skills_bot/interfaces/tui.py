"""Textual TUI for agent-skills-bot."""

from __future__ import annotations

import logging

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Button, Input, Static, RichLog
from textual import work

from agent_skills_bot.core.agent import run
from agent_skills_bot.utils.logger import setup_textual_logger


class AgentApp(App):
    CSS = """
    Screen { align: center middle; }
    #root { width: 90%; height: 90%; }
    Input { width: 100%; }
    RichLog { height: 1fr; border: solid gray; }
    #status { height: 1; color: yellow; }
    """

    def compose(self) -> ComposeResult:
        yield Container(
            Input(placeholder="Enter a request, e.g. find some skills which can convert pdf to markdown", id="query"),
            Button("Run", id="run", variant="primary"),
            Static("", id="status"),
            RichLog(id="log"),
            id="root",
        )

    def on_mount(self) -> None:
        setup_textual_logger(self.query_one(RichLog))
        logging.getLogger("app.core").info("Ready")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run":
            self.start_query()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "query":
            self.start_query()

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    @work(exclusive=True)
    async def start_query(self) -> None:
        query = self.query_one("#query", Input).value.strip()
        if not query:
            self._set_status("Please enter a query.")
            return

        self._set_status("Running...")
        log = self.query_one(RichLog)
        log.clear()

        try:
            result = await run(query)
        except Exception as exc:
            self._set_status("Failed")
            logging.getLogger("app.core").error(str(exc))
            return

        self._set_status("Done")
        log.write(result.raw_output or "(no output)")


def run_tui() -> None:
    AgentApp().run()


if __name__ == "__main__":
    run_tui()
