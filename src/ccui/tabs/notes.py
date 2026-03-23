"""Notes/Plans tab handler — parameterized by kind ("plan" or "note")."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import DataTable

from ccui.config import read_file_content
from ccui.notes import NoteInfo, create_note, delete_note, rename_note, scan_notes
from ccui.tabs.base import TabHandler

if TYPE_CHECKING:
    from ccui.store import AppStore


class NotesTab(TabHandler):
    """Handles both Plans and Notes tabs (parameterized by kind)."""

    has_preview = True

    def __init__(self, kind: str) -> None:
        self.kind = kind  # "plan" or "note"
        self.tab_id = f"tab-{kind}s"
        self.tab_label = f"{kind.capitalize()}s"
        self.table_id = f"pv-{kind}-table"
        self._items: list[NoteInfo] = []

    def setup_columns(self, table: DataTable) -> None:
        table.add_columns("Title", "Date", "Session")

    def refresh(
        self, table: DataTable, store: AppStore, project: str, project_path: str
    ) -> None:
        self._items = scan_notes(project_path, self.kind)
        table.clear()
        for n in self._items:
            linked = ""
            if n.session_id:
                s = next(
                    (s for s in store.sessions if s.session_id == n.session_id), None
                )
                linked = f"→ {store.display_title(s)}" if s else f"→ {n.session_id[:8]}"
            table.add_row(n.title, n.created, linked, key=str(n.path))

    def get_selected(self, table: DataTable) -> NoteInfo | None:
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        path_str = row_key.value
        for item in self._items:
            if str(item.path) == path_str:
                return item
        return None

    def view_info(self, item: Any, store: AppStore) -> tuple[str, str, None] | None:
        note: NoteInfo = item
        content = read_file_content(note.path)
        header = f" {note.kind.upper()}: {note.title}"
        return header, content, None

    def delete_info(self, item: Any, store: AppStore) -> tuple[str, callable] | None:
        note: NoteInfo = item
        return f"Delete {note.kind} '{note.title}'?", lambda: delete_note(note)

    def get_preview(self, item: Any, store: AppStore) -> Text | str:
        note: NoteInfo = item
        result = Text()
        summary = store.note_summaries.get(str(note.path), "")
        if summary:
            result.append(f"  ▸ {summary}\n", style="white on blue")
        content = read_file_content(note.path)
        # Strip frontmatter
        lines = content.splitlines()
        if lines and lines[0].strip() == "---":
            for i, line in enumerate(lines[1:], 1):
                if line.strip() == "---":
                    lines = lines[i + 1 :]
                    break
        # Skip leading blank lines
        while lines and not lines[0].strip():
            lines = lines[1:]
        preview_lines = lines[:8]
        for line in preview_lines:
            result.append(f"  {line}\n")
        if len(lines) > 8:
            result.append(f"  ... ({len(lines) - 8} more lines)\n", style="dim")
        return result if result.plain else "  (empty)"

    def edit_path(self, item: Any) -> Path | None:
        return item.path

    def rename_info(
        self, item: Any, store: AppStore
    ) -> tuple[str, str, callable] | None:
        note: NoteInfo = item

        def do_rename(new_name: str) -> None:
            rename_note(note, new_name)

        return "Rename:", note.title, do_rename

    def create_label(self) -> str | None:
        return self.kind

    def do_create(
        self, project_path: str, title: str
    ) -> tuple[str | None, Path | None]:
        note = create_note(project_path, self.kind, title)
        return f"Created {self.kind}: {title}", note.path
