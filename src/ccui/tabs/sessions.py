"""Session tab handlers — Timeline (all sessions) and ProjectSessions (per-project)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import DataTable

from ccui.archive import toggle_archive
from ccui.data import SessionInfo, delete_session, load_session_messages
from ccui.tabs.base import TabHandler

if TYPE_CHECKING:
    from ccui.store import AppStore


TITLE_MAX_WIDTH = 60


def _truncate(text: str, limit: int = TITLE_MAX_WIDTH) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


class _BaseSessionsTab(TabHandler):
    """Shared logic for session-based tabs."""

    has_preview = True
    supports_archive = True

    def __init__(self) -> None:
        self._items: list[SessionInfo] = []

    def get_selected(self, table: DataTable) -> SessionInfo | None:
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        sid = row_key.value
        for s in self._items:
            if s.session_id == sid:
                return s
        return None

    def view_info(
        self, item: Any, store: AppStore
    ) -> tuple[str, str, SessionInfo] | None:
        session: SessionInfo = item
        messages = load_session_messages(session.jsonl_path)
        lines: list[str] = []
        for msg in messages:
            role = "USER" if msg["role"] == "user" else "CLAUDE"
            lines.append(f"{'─' * 60}")
            lines.append(f"  {role}:")
            lines.append("")
            lines.append(msg["text"])
            lines.append("")
        content = "\n".join(lines) if lines else "(no messages)"
        title = store.display_title(session)
        header = f" {session.project_name} | {title} | {session.message_count} msgs | {session.date_str}"
        return header, content, session

    def delete_info(self, item: Any, store: AppStore) -> tuple[str, callable] | None:
        session: SessionInfo = item
        title = store.display_title(session)[:40]

        def do_delete() -> bool:
            if delete_session(session):
                store.remove_session(session.session_id)
                return True
            return False

        return f"Delete session '{title}'?", do_delete

    def toggle_archive(self, item: Any, store: AppStore) -> str | None:
        session: SessionInfo = item
        new_state = toggle_archive(session.session_id)
        store.reload_archived()
        label = "Archived" if new_state else "Unarchived"
        return f"{label}: {store.display_title(session)[:40]}"

    def get_preview(self, item: Any, store: AppStore) -> Text | str:
        session: SessionInfo = item
        result = Text()
        summary = store.display_summary(session)
        if summary:
            result.append(f"  ▸ {summary}\n", style="white on blue")
        messages = load_session_messages(session.jsonl_path, max_messages=4)
        for msg in messages:
            role = "USER" if msg["role"] == "user" else "ASST"
            text = msg["text"].replace("\n", " ")[:100]
            result.append(f"  {role}: {text}\n")
        return result if result.plain else "  (no messages)"

    def get_export_content(self, item: Any, store: AppStore) -> tuple[str, str] | None:
        session: SessionInfo = item
        messages = load_session_messages(session.jsonl_path)
        lines: list[str] = []
        for msg in messages:
            role = "USER" if msg["role"] == "user" else "CLAUDE"
            lines.append(f"### {role}\n\n{msg['text']}\n")
        return store.display_title(session), "\n".join(lines)


class TimelineTab(_BaseSessionsTab):
    """All sessions across all projects, sorted by time."""

    tab_id = "timeline"
    tab_label = "Timeline"
    table_id = "tl-table"

    def setup_columns(self, table: DataTable) -> None:
        table.add_columns("", "Project", "Title", "Msgs", "Date")

    def refresh(
        self, table: DataTable, store: AppStore, project: str, project_path: str
    ) -> None:
        self._items = store.visible_sessions()
        table.clear()
        for s in self._items:
            archived = "[A]" if s.session_id in store.archived_ids else ""
            table.add_row(
                archived,
                s.project_name,
                _truncate(store.display_title(s)),
                str(s.message_count),
                s.date_str,
                key=s.session_id,
            )


class SessionsTab(_BaseSessionsTab):
    """Sessions for a single project."""

    tab_id = "tab-sessions"
    tab_label = "Sessions"
    table_id = "pv-session-table"

    def setup_columns(self, table: DataTable) -> None:
        table.add_columns("", "Title", "Msgs", "Date")

    def refresh(
        self, table: DataTable, store: AppStore, project: str, project_path: str
    ) -> None:
        self._items = store.visible_sessions(project)
        table.clear()
        for s in self._items:
            archived = "[A]" if s.session_id in store.archived_ids else ""
            table.add_row(
                archived,
                _truncate(store.display_title(s)),
                str(s.message_count),
                s.date_str,
                key=s.session_id,
            )
