"""TimelineScreen — all sessions across all projects, sorted by time."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from ccui.screens.base import ItemListScreen
from ccui.tabs import TimelineTab
from ccui.tabs.base import TabHandler


class TimelineScreen(ItemListScreen):

    _KEY_MAP = {
        **ItemListScreen._KEY_MAP,
        "d": "_action_delete_item",
        "a": "_action_toggle_archive",
        "H": "_action_toggle_show_archived",
        "x": "_action_export_item",
        "o": "_action_resume_session",
        "S": "_action_summarize_all",
    }

    def __init__(self) -> None:
        super().__init__()
        self._timeline = TimelineTab()

    # ── Compose ───────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield from self._compose_search_bar()
        with Vertical(id="timeline-view"):
            yield DataTable(id="tl-table", cursor_type="row", classes="session-table")
            yield Static("", id="tl-table-preview", classes="preview")
        yield Static("", id="summarize-bar", classes="summarize-bar")
        yield from self._compose_footer()

    # ── Abstract implementations ──────────────────────────────────────

    def _setup_tables(self) -> None:
        tl = self.query_one("#tl-table", DataTable)
        tl.clear(columns=True)
        self._timeline.setup_columns(tl)

    def _get_active_handler(self) -> TabHandler | None:
        return self._timeline

    def _get_active_table(self) -> DataTable | None:
        return self.query_one("#tl-table", DataTable)

    def _do_refresh(self) -> None:
        self._refreshing = True
        tl = self.query_one("#tl-table", DataTable)
        self._timeline.refresh(tl, self.store, "", "")
        self._refreshing = False

    def _update_status(self) -> None:
        total = len(self.store.sessions)
        archived = sum(
            1 for s in self.store.sessions if s.session_id in self.store.archived_ids
        )
        table = self._get_active_table()
        visible = table.row_count if table else 0
        show_a = " | +archived" if self.store.show_archived else ""
        status = f" [Timeline] {visible}/{total} sessions | {archived} archived{show_a}"
        if self.store.search_query:
            status += f" | /{self.store.search_query}"
        self.query_one("#status-bar", Static).update(status)
        self.query_one("#help-bar", Static).update(
            " q:Quit  Tab:View  Enter:Open  o:Resume  d:Del  a:Archive"
            "  H:Hidden  x:Export  S:Summarize  /:Search  R:Reload  T:Theme"
        )

    # ── Batch summarize ───────────────────────────────────────────────

    def _action_summarize_all(self) -> None:
        from ccui.summarize import sessions_needing_summary

        pending = sessions_needing_summary(self.store)
        if not pending:
            self.notify("All sessions already have summaries")
            return
        bar = self.query_one("#summarize-bar", Static)
        bar.display = True
        self._update_progress_bar(0, len(pending), "starting...")
        self.run_worker(self._do_summarize, thread=True)

    def _do_summarize(self) -> None:
        from ccui.summarize import generate_batch, sessions_needing_summary

        total = len(sessions_needing_summary(self.store))

        def on_progress(current: int, total: int, title: str) -> None:
            self.app.call_from_thread(self._update_progress_bar, current, total, title)

        def on_done(count: int) -> None:
            self.app.call_from_thread(self._on_summarize_done, count)

        generate_batch(self.store, on_progress=on_progress, on_done=on_done)

    def _update_progress_bar(self, current: int, total: int, title: str) -> None:
        bar = self.query_one("#summarize-bar", Static)
        width = max(self.size.width - 30, 10)
        filled = int(width * current / total) if total > 0 else 0
        empty = width - filled
        pct = int(100 * current / total) if total > 0 else 0
        bar.update(
            f" Summarize: [{'█' * filled}{'░' * empty}] "
            f"{current}/{total} ({pct}%)  {title}"
        )

    def _on_summarize_done(self, count: int) -> None:
        bar = self.query_one("#summarize-bar", Static)
        bar.update(f" Done! Summarized {count} sessions")
        self.set_timer(3.0, self._hide_progress_bar)
        self.store.reload()
        self._refresh_all()

    def _hide_progress_bar(self) -> None:
        bar = self.query_one("#summarize-bar", Static)
        bar.display = False
