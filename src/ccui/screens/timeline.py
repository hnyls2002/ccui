"""TimelineScreen — all sessions across all projects, sorted by time."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Header, Static

from ccui.screens.base import ItemListScreen
from ccui.tabs import TimelineTab
from ccui.tabs.base import TabHandler


class TimelineScreen(ItemListScreen):

    _KEY_MAP = {
        **ItemListScreen._KEY_MAP,
        "d": "_action_delete_item",
        "a": "_action_toggle_archive",
        "H": "_action_toggle_show_archived",
        "r": "_action_rename",
        "x": "_action_export_item",
        "o": "_action_resume_session",
    }

    def __init__(self) -> None:
        super().__init__()
        self._timeline = TimelineTab()

    # ── Compose ───────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        yield from self._compose_search_bar()
        with Vertical(id="timeline-view"):
            yield DataTable(id="tl-table", cursor_type="row", classes="session-table")
            yield Static("", id="tl-table-preview", classes="preview")
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
            "  H:Hidden  r:Rename  x:Export  /:Search  T:Theme"
        )
