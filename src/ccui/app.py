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
        self.exit()

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
    import sys

    args = sys.argv[1:]

    # Subcommand: ccui usage [days] [-w/--watch [interval]]
    if args and args[0] == "usage":
        from ccui.usage import print_usage, sync_all_sessions

        rest = args[1:]
        days = 10
        watch = False
        show_extra = False
        interval = 3
        i = 0
        while i < len(rest):
            if rest[i] in ("-w", "--watch"):
                watch = True
                # optional interval argument
                if i + 1 < len(rest) and rest[i + 1].isdigit():
                    interval = int(rest[i + 1])
                    i += 1
            elif rest[i] == "--extra":
                show_extra = True
            elif rest[i].isdigit():
                days = int(rest[i])
            i += 1

        if watch:
            import time

            try:
                while True:
                    print("\033[2J\033[H", end="")  # clear screen
                    sync_all_sessions()
                    print_usage(days, show_extra=show_extra)
                    print(f"\n  Refreshing every {interval}s — Ctrl+C to stop")
                    time.sleep(interval)
            except KeyboardInterrupt:
                pass
        else:
            sync_all_sessions()
            print_usage(days, show_extra=show_extra)
        return

    # Subcommand: ccui summarize <session_id> [--force] [--full]
    if args and args[0] == "summarize":
        if len(args) < 2:
            print(
                "Usage: ccui summarize <session_id> [--force] [--full]", file=sys.stderr
            )
            sys.exit(1)
        session_id = args[1]
        force = "--force" in args
        full = "--full" in args

        from ccui.store import AppStore
        from ccui.summarize import summarize_one

        store = AppStore()
        store.reload()

        matches = [s for s in store.sessions if s.session_id.startswith(session_id)]
        if not matches:
            print(f"No session found matching '{session_id}'", file=sys.stderr)
            sys.exit(1)
        if len(matches) > 1:
            print(
                f"Ambiguous: {', '.join(s.session_id[:8] for s in matches)}",
                file=sys.stderr,
            )
            sys.exit(1)

        session = matches[0]
        result = summarize_one(session, store, force=force, full=full)
        if result:
            title, summary = result
            print(f"{title} — {summary}")
        else:
            title = store.display_title(session)
            summary = store.display_summary(session)
            if summary:
                print(f"{title} — {summary}")
            else:
                print("No summary generated", file=sys.stderr)
                sys.exit(1)
        return

    # TUI mode: sync token usage in background before launching
    from ccui.usage import sync_all_sessions

    sync_all_sessions()

    app = CcuiApp()
    app.run()


if __name__ == "__main__":
    main()
