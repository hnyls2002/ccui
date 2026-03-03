"""ccui — Claude Code TUI Manager built with textual."""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from ccui.screens import ProjectScreen, TimelineScreen
from ccui.store import AppStore


class CcuiApp(App):
    TITLE = "ccui"
    CSS_PATH = "app.tcss"

    BINDINGS = [Binding("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.store = AppStore()
        self._view_mode = "timeline"

    def on_mount(self) -> None:
        self.store.reload()
        self.install_screen(TimelineScreen(), name="timeline")
        self.install_screen(ProjectScreen(), name="project")
        self.push_screen("timeline")

    def action_switch_view(self) -> None:
        if self._view_mode == "timeline":
            self._view_mode = "project"
        else:
            self._view_mode = "timeline"
        self.switch_screen(self._view_mode)


def main() -> None:
    app = CcuiApp()
    app.run()


if __name__ == "__main__":
    main()
