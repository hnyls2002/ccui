"""Modal dialogs — ConfirmDialog and InputDialog."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class ConfirmDialog(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
    ]
    DEFAULT_CSS = """
    ConfirmDialog { align: center middle; background: rgba(0, 0, 0, 0.6); }
    #confirm-box {
        width: 60; height: auto; max-height: 10;
        border: thick $error; background: $surface; padding: 1 2;
    }
    #confirm-msg { margin-bottom: 1; text-style: bold; }
    #confirm-hint { color: $text-muted; }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(self._message, id="confirm-msg")
            yield Label("  y = confirm  |  n / q / Esc = cancel", id="confirm-hint")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class InputDialog(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    InputDialog { align: center middle; }
    #input-box {
        width: 60; height: 9;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    """

    def __init__(self, title: str, placeholder: str = "", default: str = "") -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="input-box"):
            yield Label(self._title)
            yield Input(
                placeholder=self._placeholder, value=self._default, id="dialog-input"
            )
            yield Label("[Enter] confirm / [Esc] cancel", classes="dim")

    @on(Input.Submitted, "#dialog-input")
    def on_submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)
