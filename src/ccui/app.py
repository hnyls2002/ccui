"""ccui — Claude Code TUI Manager built with textual."""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from ccui.screens import ProjectScreen, TimelineScreen
from ccui.store import AppStore
from ccui.themes import CUSTOM_THEMES, THEME_CYCLE, load_theme_name, save_theme_name


class CcuiApp(App):
    TITLE = "ccui"
    CSS_PATH = "app.tcss"

    BINDINGS = [Binding("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.store = AppStore()
        self._view_mode = "timeline"
        for theme in CUSTOM_THEMES:
            self.register_theme(theme)
        self.theme = load_theme_name()

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

    def action_quit(self) -> None:
        # Cancel any running summarize worker before exiting
        try:
            tl = self.get_screen("timeline")
            tl._summarize_cancel.set()
        except Exception:
            pass
        super().action_quit()

    def action_cycle_theme(self) -> None:
        current = self.theme
        try:
            idx = THEME_CYCLE.index(current)
            nxt = THEME_CYCLE[(idx + 1) % len(THEME_CYCLE)]
        except ValueError:
            nxt = THEME_CYCLE[0]
        self.theme = nxt
        save_theme_name(nxt)
        self.notify(f"Theme: {nxt}")


def main() -> None:
    app = CcuiApp()
    app.run()


if __name__ == "__main__":
    main()
