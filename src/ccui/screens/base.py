"""Base screen classes for ccui views.

BaseViewScreen — truly generic: store, key dispatch, search, status bar, lifecycle.
ItemListScreen — DataTable + TabHandler: vim nav, cursor, preview, reusable CRUD methods.

KEY_MAP design: ItemListScreen only binds navigation keys.
CRUD actions are provided as methods but NOT bound — each screen opts in via its own KEY_MAP.
"""

from __future__ import annotations

import os
import subprocess
from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from textual import on
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Input, Static

from ccui.data import resolve_cwd
from ccui.logo import LOGO
from ccui.notes import create_note
from ccui.screens.dialogs import ConfirmDialog, InputDialog
from ccui.screens.viewer import ContentViewScreen
from ccui.tabs.base import TabHandler

if TYPE_CHECKING:
    from ccui.store import AppStore


# ═══════════════════════════════════════════════════════════════════════
# Layer 1 — truly generic screen base
# ═══════════════════════════════════════════════════════════════════════


class BaseViewScreen(Screen):
    """Generic view screen: store access, key dispatch, search, status bar.

    Subclass this directly for non-DataTable screens (editors, dashboards).
    Subclass ItemListScreen instead for DataTable + TabHandler screens.
    """

    _KEY_MAP: dict[str, str] = {
        "tab": "_action_switch_view",
        "slash": "_action_search",
        "T": "_action_cycle_theme",
        "R": "_action_reload",
    }

    @property
    def store(self) -> AppStore:
        return self.app.store  # type: ignore[attr-defined]

    # ── Lifecycle ─────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._do_setup()
        self._refresh_all()
        self.call_after_refresh(self._focus_default)

    def on_screen_resume(self) -> None:
        self._refresh_all()
        self.call_after_refresh(self._focus_default)

    def _do_setup(self) -> None:
        """One-time initialization on first mount. Override in subclasses."""

    def _focus_default(self) -> None:
        """Set focus after mount/resume. Override in subclasses."""

    # ── Refresh ───────────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        self._do_refresh()
        self._update_status()

    @abstractmethod
    def _do_refresh(self) -> None: ...

    @abstractmethod
    def _update_status(self) -> None: ...

    # ── Key dispatch ──────────────────────────────────────────────────

    def on_key(self, event) -> None:  # noqa: ANN001
        search_bar = self.query_one("#search-bar", Input)
        if search_bar.display and search_bar.has_focus:
            if event.key == "escape":
                search_bar.display = False
                self.store.search_query = ""
                self._refresh_all()
                self._focus_default()
                event.prevent_default()
                event.stop()
            return

        action = self._KEY_MAP.get(event.key)
        if action:
            getattr(self, action)()
            event.prevent_default()
            event.stop()

    # ── Search ────────────────────────────────────────────────────────

    def _action_switch_view(self) -> None:
        self.app.action_switch_view()  # type: ignore[attr-defined]

    def _action_cycle_theme(self) -> None:
        self.app.action_cycle_theme()  # type: ignore[attr-defined]
        self._update_status()

    def _action_reload(self) -> None:
        self.store.reload()
        self._refresh_all()
        self.notify("Reloaded")

    def _action_search(self) -> None:
        search_bar = self.query_one("#search-bar", Input)
        search_bar.display = True
        search_bar.value = self.store.search_query
        search_bar.focus()

    @on(Input.Submitted, "#search-bar")
    def _on_search_submitted(self, event: Input.Submitted) -> None:
        self.store.search_query = event.value.strip()
        self.query_one("#search-bar", Input).display = False
        self._refresh_all()
        self._focus_default()

    @on(Input.Changed, "#search-bar")
    def _on_search_changed(self, event: Input.Changed) -> None:
        self.store.search_query = event.value.strip()
        self._refresh_all()

    # ── Compose helpers ───────────────────────────────────────────────

    def _compose_search_bar(self) -> ComposeResult:
        yield Input(placeholder="Search... (Esc to close)", id="search-bar")

    def _compose_footer(self) -> ComposeResult:
        yield Static("", id="status-bar")
        yield Static("", id="help-bar")
        yield Static(LOGO, id="logo-bar")


# ═══════════════════════════════════════════════════════════════════════
# Layer 2 — DataTable + TabHandler item-list screen
# ═══════════════════════════════════════════════════════════════════════


class ItemListScreen(BaseViewScreen):
    """Screen with DataTable(s) driven by TabHandler(s).

    Provides: vim navigation, cursor save/restore, preview, reusable CRUD methods.

    KEY_MAP only binds navigation. Subclasses opt in to CRUD actions::

        _KEY_MAP = {
            **ItemListScreen._KEY_MAP,
            "d": "_action_delete_item",
            "r": "_action_rename",
            # ... only what this screen needs
        }
    """

    _KEY_MAP: dict[str, str] = {
        **BaseViewScreen._KEY_MAP,
        "j": "_action_vim_down",
        "k": "_action_vim_up",
        "g": "_action_scroll_top",
        "G": "_action_scroll_bottom",
        "down": "_action_vim_down",
        "up": "_action_vim_up",
    }

    def __init__(self) -> None:
        super().__init__()
        self._refreshing = False

    # ── Setup / focus ─────────────────────────────────────────────────

    def _do_setup(self) -> None:
        self._setup_tables()

    @abstractmethod
    def _setup_tables(self) -> None: ...

    def _focus_default(self) -> None:
        table = self._get_active_table()
        if table:
            table.focus()

    # ── Refresh (with cursor save/restore) ────────────────────────────

    def _refresh_all(self) -> None:
        table = self._get_active_table()
        saved_row = table.cursor_row if table and table.row_count > 0 else 0
        super()._refresh_all()
        table = self._get_active_table()
        if table and table.row_count > 0:
            table.move_cursor(row=min(saved_row, table.row_count - 1))

    # ── Abstract: handler / table resolution ──────────────────────────

    @abstractmethod
    def _get_active_handler(self) -> TabHandler | None: ...

    @abstractmethod
    def _get_active_table(self) -> DataTable | None: ...

    def _get_active_item(self) -> tuple[TabHandler | None, object | None]:
        handler = self._get_active_handler()
        if not handler:
            return None, None
        table = self.query_one(f"#{handler.table_id}", DataTable)
        return handler, handler.get_selected(table)

    # ── Preview ───────────────────────────────────────────────────────

    def _update_preview(self) -> None:
        handler = self._get_active_handler()
        if not handler or not handler.has_preview:
            return
        table = self.query_one(f"#{handler.table_id}", DataTable)
        item = handler.get_selected(table)
        try:
            preview = self.query_one(f"#{handler.table_id}-preview", Static)
        except Exception:
            return
        if item:
            preview.update(handler.get_preview(item, self.store))
        else:
            preview.update("")

    # ── DataTable event handlers ──────────────────────────────────────

    @on(DataTable.RowHighlighted)
    def _on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._refreshing:
            return
        handler = self._get_active_handler()
        if handler and event.data_table.id == handler.table_id:
            self._update_preview()

    @on(DataTable.RowSelected)
    def _on_row_selected(self, event: DataTable.RowSelected) -> None:
        if self._refreshing:
            return
        handler = self._get_active_handler()
        if handler and event.data_table.id == handler.table_id:
            self._action_view_item()

    # ── Reusable CRUD actions (NOT in KEY_MAP — screens opt in) ───────

    def _action_view_item(self) -> None:
        handler, item = self._get_active_item()
        if not handler or not item:
            return
        info = handler.view_info(item, self.store)
        if not info:
            return
        header, content, session = info
        project_path = self._resolve_project_path(item, session)
        self.app.push_screen(
            ContentViewScreen(
                header, content, session=session, project_path=project_path
            )
        )

    def _action_delete_item(self) -> None:
        handler, item = self._get_active_item()
        if not handler or not item:
            return
        info = handler.delete_info(item, self.store)
        if not info:
            return
        self._confirm_and_delete(*info)

    def _action_toggle_archive(self) -> None:
        handler, item = self._get_active_item()
        if not handler or not item or not handler.supports_archive:
            return
        msg = handler.toggle_archive(item, self.store)
        if msg:
            table = self._get_active_table()
            session_id = getattr(item, "session_id", "")
            is_archived = session_id in self.store.archived_ids

            if is_archived and not self.store.show_archived and table:
                # Archived and hidden → remove the single row
                row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
                table.remove_row(row_key)
                self._update_preview()
            elif table and table.row_count > 0:
                # Still visible → flip the archive indicator (first column)
                row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
                first_col = next(iter(table.columns))
                table.update_cell(row_key, first_col, "[A]" if is_archived else "")

            self._update_status()
            self.notify(msg)

    def _action_toggle_show_archived(self) -> None:
        self.store.show_archived = not self.store.show_archived
        self._refresh_all()

    def _action_rename(self) -> None:
        handler, item = self._get_active_item()
        if not handler or not item:
            return
        info = handler.rename_info(item, self.store)
        if not info:
            return
        dialog_title, current, apply_fn = info
        table = self._get_active_table()
        row_key = None
        if table and table.row_count > 0:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)

        def on_name(name: str | None) -> None:
            if name:
                apply_fn(name)
                if row_key is not None and table and table.row_count > 0:
                    first_col = next(iter(table.columns))
                    table.update_cell(row_key, first_col, name)
                    self._update_preview()
                    self._update_status()
                else:
                    self._refresh_all()

        self.app.push_screen(
            InputDialog(dialog_title, default=current), callback=on_name
        )

    def _action_edit_external(self) -> None:
        handler, item = self._get_active_item()
        path = handler.edit_path(item) if handler and item else None
        if not path:
            self.notify("Nothing to edit", severity="warning")
            return
        self._open_in_editor(path)

    def _resume_session(self, *, dangerous_skip: bool = False) -> None:
        handler, item = self._get_active_item()
        if not handler or not item:
            return
        session_id = getattr(item, "session_id", "")
        project_path = getattr(item, "project_path", "")
        if not session_id:
            self.notify("Not a session", severity="warning")
            return
        cwd = resolve_cwd(project_path)
        if project_path and cwd != project_path:
            self.notify(f"Directory gone, using {cwd or 'HOME'}", severity="warning")
        cmd = ["claude", "--resume", session_id]
        if dangerous_skip:
            cmd.append("--dangerously-skip-permissions")
        with self.app.suspend():
            subprocess.call(cmd, cwd=cwd)
        self._refresh_all()

    def _action_resume_session(self) -> None:
        self._resume_session()

    def _action_resume_session_dangerous(self) -> None:
        self._resume_session(dangerous_skip=True)

    def _action_export_item(self) -> None:
        handler, item = self._get_active_item()
        if not handler or not item:
            return
        export = handler.get_export_content(item, self.store)
        if not export:
            return
        default_title, content = export
        pp = self._resolve_project_path(item)
        if not pp:
            self.notify("No project path", severity="warning")
            return

        def on_kind(kind: str | None) -> None:
            if kind not in ("plan", "note"):
                return

            def on_title(t: str | None) -> None:
                if not t:
                    return
                session_id = getattr(item, "session_id", "")
                create_note(pp, kind, t, session_id, content)
                self._refresh_all()
                self.notify(f"Exported as {kind}: {t}")

            self.app.push_screen(
                InputDialog("Title:", default=default_title), callback=on_title
            )

        self.app.push_screen(
            InputDialog("Export as (plan/note):", "plan"), callback=on_kind
        )

    # ── Helpers ───────────────────────────────────────────────────────

    def _resolve_project_path(self, item: object, session: object | None = None) -> str:
        """Get project path from item/session. Override for view-specific fallback."""
        if session and hasattr(session, "project_path"):
            return session.project_path
        return getattr(item, "project_path", "")

    def _confirm_and_delete(self, message: str, delete_fn: object) -> None:
        table = self._get_active_table()
        row_key = None
        if table and table.row_count > 0:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)

        def on_confirm(confirmed: bool) -> None:
            if confirmed and delete_fn():
                if row_key is not None and table:
                    table.remove_row(row_key)
                    self._update_preview()
                    self._update_status()
                else:
                    self._refresh_all()
                self.notify("Deleted")

        self.app.push_screen(ConfirmDialog(message), callback=on_confirm)

    def _open_in_editor(self, path: Path) -> None:
        editor = os.environ.get("EDITOR", "vim")
        with self.app.suspend():
            subprocess.call([editor, str(path)])
        self._refresh_all()

    # ── Vim navigation ────────────────────────────────────────────────

    def _action_vim_down(self) -> None:
        table = self._get_active_table()
        if table and table.row_count > 0:
            table.move_cursor(row=min(table.cursor_row + 1, table.row_count - 1))

    def _action_vim_up(self) -> None:
        table = self._get_active_table()
        if table and table.row_count > 0:
            table.move_cursor(row=max(table.cursor_row - 1, 0))

    def _action_scroll_top(self) -> None:
        table = self._get_active_table()
        if table and table.row_count > 0:
            table.move_cursor(row=0)

    def _action_scroll_bottom(self) -> None:
        table = self._get_active_table()
        if table and table.row_count > 0:
            table.move_cursor(row=table.row_count - 1)
