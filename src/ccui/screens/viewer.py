"""Content viewer screen — session detail, note/plan, skill, rule, etc."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea

from ccui.notes import create_note
from ccui.screens.dialogs import InputDialog
from ccui.titles import get_title

if TYPE_CHECKING:
    from ccui.data import SessionInfo


class ContentViewScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "back", "Back", priority=True),
        Binding("q", "back", "Back", priority=True),
        Binding("x", "export", "Export to plan/note", priority=True),
        Binding("j", "scroll_down", "Down", show=False, priority=True),
        Binding("k", "scroll_up", "Up", show=False, priority=True),
        Binding("h", "cursor_left", "Left", show=False, priority=True),
        Binding("l", "cursor_right", "Right", show=False, priority=True),
        Binding("g", "scroll_top", "Top", show=False, priority=True),
        Binding("G", "scroll_bottom", "Bottom", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    ContentViewScreen { align: center middle; }
    #cv-box { width: 100%; height: 100%; border: thick $accent; background: $surface; }
    #cv-header { height: 3; padding: 0 2; background: $primary; color: $text; }
    #cv-content { height: 1fr; padding: 0 1; }
    """

    def __init__(
        self,
        header: str,
        content: str,
        session: SessionInfo | None = None,
        project_path: str = "",
    ) -> None:
        super().__init__()
        self._header = header
        self._content = content
        self._session = session
        self._project_path = project_path

    def compose(self) -> ComposeResult:
        with Vertical(id="cv-box"):
            yield Static(self._header, id="cv-header")
            yield TextArea(id="cv-content", read_only=True)

    def on_mount(self) -> None:
        self.query_one("#cv-content", TextArea).text = self._content

    def action_scroll_down(self) -> None:
        ta = self.query_one("#cv-content", TextArea)
        ta.action_cursor_down()

    def action_scroll_up(self) -> None:
        ta = self.query_one("#cv-content", TextArea)
        ta.action_cursor_up()

    def action_cursor_left(self) -> None:
        ta = self.query_one("#cv-content", TextArea)
        ta.action_cursor_left()

    def action_cursor_right(self) -> None:
        ta = self.query_one("#cv-content", TextArea)
        ta.action_cursor_right()

    def action_scroll_top(self) -> None:
        ta = self.query_one("#cv-content", TextArea)
        ta.move_cursor((0, 0))

    def action_scroll_bottom(self) -> None:
        ta = self.query_one("#cv-content", TextArea)
        last_line = ta.document.line_count - 1
        ta.move_cursor((last_line, 0))

    def action_back(self) -> None:
        self.dismiss(None)

    def action_export(self) -> None:
        if not self._session or not self._project_path:
            self.notify("No session to export", severity="warning")
            return

        def on_kind(kind: str | None) -> None:
            if kind not in ("plan", "note"):
                return
            title = (
                get_title(self._session.session_id) or self._session.first_prompt[:60]
            )

            def on_title(t: str | None) -> None:
                if not t:
                    return
                create_note(
                    self._project_path, kind, t, self._session.session_id, self._content
                )
                self.notify(f"Exported as {kind}: {t}")

            self.app.push_screen(
                InputDialog("Title:", default=title), callback=on_title
            )

        self.app.push_screen(
            InputDialog("Export as (plan/note):", "plan"), callback=on_kind
        )
