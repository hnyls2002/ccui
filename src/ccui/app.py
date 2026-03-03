"""ccui — Claude Code TUI Manager built with textual."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    DataTable,
    Header,
    Input,
    OptionList,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from ccui.config import get_global_config, get_project_config
from ccui.notes import create_note
from ccui.screens import ConfirmDialog, ContentViewScreen, InputDialog
from ccui.store import AppStore
from ccui.tabs import NotesTab, RulesTab, SessionsTab, SkillsTab, TimelineTab
from ccui.tabs.base import TabHandler

# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------


class CcuiApp(App):
    TITLE = "ccui"
    CSS_PATH = "app.tcss"

    BINDINGS = [Binding("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.store = AppStore()

        # View state
        self._view_mode = "timeline"
        self._selected_project: str | None = None
        self._selected_project_path: str = ""
        self._active_tab = "sessions"
        self._refreshing = False

        # Tab handlers — one dict for project tabs, plus the timeline handler
        self._timeline = TimelineTab()
        self._project_tabs: dict[str, TabHandler] = {
            "sessions": SessionsTab(),
            "plans": NotesTab("plan"),
            "notes": NotesTab("note"),
            "skills": SkillsTab(),
            "rules": RulesTab(),
        }

    # ── Compose ───────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search... (Esc to close)", id="search-bar")

        # Timeline view
        with Vertical(id="timeline-view"):
            yield DataTable(id="tl-table", cursor_type="row", classes="session-table")
            yield Static("", id="tl-preview", classes="preview")

        # Project view (hidden initially)
        with Horizontal(id="project-view", classes="hidden"):
            yield OptionList(id="project-list")
            with Vertical(id="right-panel"):
                with TabbedContent(id="project-tabs"):
                    # Table-based tabs from handlers
                    for handler in self._project_tabs.values():
                        with TabPane(handler.tab_label, id=handler.tab_id):
                            yield DataTable(
                                id=handler.table_id,
                                cursor_type="row",
                                classes="session-table",
                            )
                            if handler.has_preview:
                                yield Static(
                                    "",
                                    id=f"{handler.table_id}-preview",
                                    classes="preview",
                                )
                    # Config tab (special — no DataTable)
                    with TabPane("Config", id="tab-config"):
                        yield Static("", id="config-content")

        yield Static("", id="status-bar")
        yield Static("", id="help-bar")

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.store.reload()
        self._setup_all_tables()
        self._refresh_all()
        self.call_after_refresh(self._focus_active_table)

    def _focus_active_table(self) -> None:
        table = self._get_active_table()
        if table:
            table.focus()
            if table.row_count > 0:
                table.move_cursor(row=0)

    # ── Table setup ───────────────────────────────────────────────────────

    def _setup_all_tables(self) -> None:
        tl = self.query_one("#tl-table", DataTable)
        tl.clear(columns=True)
        self._timeline.setup_columns(tl)
        for handler in self._project_tabs.values():
            table = self.query_one(f"#{handler.table_id}", DataTable)
            table.clear(columns=True)
            handler.setup_columns(table)

    # ── Handler + table resolution ────────────────────────────────────────

    def _get_active_handler(self) -> TabHandler | None:
        if self._view_mode == "timeline":
            return self._timeline
        return self._project_tabs.get(self._active_tab)

    def _get_active_table(self) -> DataTable | None:
        handler = self._get_active_handler()
        if handler:
            return self.query_one(f"#{handler.table_id}", DataTable)
        return None

    def _get_active_item(self) -> tuple[TabHandler | None, object | None]:
        handler = self._get_active_handler()
        if not handler:
            return None, None
        table = self.query_one(f"#{handler.table_id}", DataTable)
        return handler, handler.get_selected(table)

    # ── Refresh ───────────────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        # Save cursor position before clearing tables
        table = self._get_active_table()
        saved_row = table.cursor_row if table and table.row_count > 0 else 0

        if self._view_mode == "timeline":
            self._refresh_timeline()
        else:
            self._refresh_project_view()
        self._update_status()

        # Restore cursor to same row (or last row if it was deleted)
        table = self._get_active_table()
        if table and table.row_count > 0:
            table.move_cursor(row=min(saved_row, table.row_count - 1))

    def _refresh_timeline(self) -> None:
        self._refreshing = True
        tl = self.query_one("#tl-table", DataTable)
        self._timeline.refresh(tl, self.store, "", "")
        self._refreshing = False

    def _refresh_project_view(self) -> None:
        self._refreshing = True
        self._refresh_project_list()
        project = self._selected_project or "GLOBAL"
        project_path = self._selected_project_path
        for handler in self._project_tabs.values():
            table = self.query_one(f"#{handler.table_id}", DataTable)
            handler.refresh(table, self.store, project, project_path)
        self._refresh_config_panel()
        self._refreshing = False

    def _refresh_project_list(self) -> None:
        project_list = self.query_one("#project-list", OptionList)
        prev = project_list.highlighted
        project_list.clear_options()
        names = self.store.project_names
        total = len(self.store.sessions)
        option_names = ["GLOBAL"] + names
        project_list.add_option(Option(f"GLOBAL ({total})"))
        for name in names:
            count = sum(1 for s in self.store.sessions if s.project_name == name)
            project_list.add_option(Option(f"{name} ({count})"))
        if self._selected_project in option_names:
            project_list.highlighted = option_names.index(self._selected_project)
        elif prev is not None and prev < len(option_names):
            project_list.highlighted = prev

    def _refresh_config_panel(self) -> None:
        gcfg = get_global_config()
        project = self._selected_project
        project_path = self._selected_project_path

        if project == "GLOBAL" or not project_path:
            lines: list[str] = []
            if gcfg.claude_md_path:
                lines.append(
                    f"Global CLAUDE.md  : found ({gcfg.claude_md_lines} lines)"
                )
            else:
                lines.append("Global CLAUDE.md  : not found")
            lines.append(
                f"Global settings   : {gcfg.permission_count} permission rules"
            )
            self.query_one("#config-content", Static).update("\n".join(lines))
            return

        cfg = get_project_config(project_path)
        lines = []
        if cfg.claude_md_path:
            lines.append(f"CLAUDE.md         : found ({cfg.claude_md_lines} lines)")
        else:
            lines.append("CLAUDE.md         : not found")
        if cfg.memory:
            m = cfg.memory
            mem_parts = []
            if m.memory_md_lines:
                mem_parts.append(f"MEMORY.md ({m.memory_md_lines} lines)")
            if m.topic_files:
                mem_parts.append(f"{len(m.topic_files)} topic files")
            lines.append(
                f"Auto Memory       : {' + '.join(mem_parts) if mem_parts else 'empty'}"
            )
        lines.append(f"settings.local    : {cfg.permission_count} permission rules")
        lines.append("")
        if gcfg.claude_md_path:
            lines.append(f"Global CLAUDE.md  : found ({gcfg.claude_md_lines} lines)")
        else:
            lines.append("Global CLAUDE.md  : not found")
        lines.append(f"Global settings   : {gcfg.permission_count} permission rules")
        self.query_one("#config-content", Static).update("\n".join(lines))

    def _update_status(self) -> None:
        total = len(self.store.sessions)
        archived = sum(
            1 for s in self.store.sessions if s.session_id in self.store.archived_ids
        )
        table = self._get_active_table()
        visible = table.row_count if table else 0
        view = (
            "Timeline"
            if self._view_mode == "timeline"
            else f"Project:{self._selected_project or '?'}"
        )
        show_a = " | +archived" if self.store.show_archived else ""
        tab = f" | {self._active_tab}" if self._view_mode == "project" else ""
        status = (
            f" [{view}] {visible}/{total} sessions | {archived} archived{show_a}{tab}"
        )
        if self.store.search_query:
            status += f" | /{self.store.search_query}"
        self.query_one("#status-bar", Static).update(status)

        help_text = " q:Quit  Tab:View  h/l:Tab  1-6:Tab#  Enter:Open  d:Del  a:Archive  H:Hidden  r:Rename  n:New  e:Edit  x:Export  /:Search"
        self.query_one("#help-bar", Static).update(help_text)

    def _update_preview(self) -> None:
        handler = self._get_active_handler()
        if not handler or not handler.has_preview:
            return
        table = self.query_one(f"#{handler.table_id}", DataTable)
        item = handler.get_selected(table)
        preview_id = (
            "tl-preview"
            if self._view_mode == "timeline"
            else f"{handler.table_id}-preview"
        )
        try:
            preview = self.query_one(f"#{preview_id}", Static)
        except Exception:
            return
        if item:
            preview.update(handler.get_preview(item, self.store))
        else:
            preview.update("")

    # ── Key dispatch ──────────────────────────────────────────────────────

    _KEY_MAP = {
        "tab": "action_switch_view",
        "h": "action_tab_prev",
        "l": "action_tab_next",
        "d": "action_delete_item",
        "a": "action_toggle_archive",
        "H": "action_toggle_show_archived",
        "r": "action_rename",
        "n": "action_new_item",
        "e": "action_edit_external",
        "x": "action_export_session",
        "slash": "action_search",
        "1": "action_goto_tab_1",
        "2": "action_goto_tab_2",
        "3": "action_goto_tab_3",
        "4": "action_goto_tab_4",
        "5": "action_goto_tab_5",
        "6": "action_goto_tab_6",
        "j": "action_vim_down",
        "k": "action_vim_up",
        "g": "action_scroll_top",
        "G": "action_scroll_bottom",
        "down": "action_vim_down",
        "up": "action_vim_up",
    }

    _TAB_ORDER = [
        "tab-sessions",
        "tab-plans",
        "tab-notes",
        "tab-skills",
        "tab-rules",
        "tab-config",
    ]

    def on_key(self, event) -> None:
        search_bar = self.query_one("#search-bar", Input)
        if search_bar.display and search_bar.has_focus:
            if event.key == "escape":
                search_bar.display = False
                self.store.search_query = ""
                self._refresh_all()
                table = self._get_active_table()
                if table:
                    table.focus()
                event.prevent_default()
                event.stop()
            return

        action = self._KEY_MAP.get(event.key)
        if action:
            getattr(self, action)()
            event.prevent_default()
            event.stop()

    # ── Event handlers ────────────────────────────────────────────────────

    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._refreshing:
            return
        handler = self._get_active_handler()
        if handler and event.data_table.id == handler.table_id:
            self._update_preview()

    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        if self._refreshing:
            return
        handler = self._get_active_handler()
        if handler and event.data_table.id == handler.table_id:
            self.action_view_item()

    @on(OptionList.OptionHighlighted, "#project-list")
    def on_project_changed(self, event: OptionList.OptionHighlighted) -> None:
        if self._refreshing or event.option is None:
            return
        text = str(event.option.prompt)
        name = text.rsplit(" (", 1)[0]
        if name == self._selected_project:
            return
        self._selected_project = name
        if name == "GLOBAL":
            self._selected_project_path = ""
        else:
            for s in self.store.sessions:
                if s.project_name == name:
                    self._selected_project_path = s.project_path
                    break
        self._refresh_project_view()
        self._update_status()

    @on(TabbedContent.TabActivated, "#project-tabs")
    def on_tab_changed(self, event: TabbedContent.TabActivated) -> None:
        tab_id = str(event.pane.id) if event.pane else ""
        mapping = {h.tab_id: key for key, h in self._project_tabs.items()}
        mapping["tab-config"] = "config"
        self._active_tab = mapping.get(tab_id, "sessions")
        self._update_status()

    @on(Input.Submitted, "#search-bar")
    def on_search_submitted(self, event: Input.Submitted) -> None:
        self.store.search_query = event.value.strip()
        self.query_one("#search-bar", Input).display = False
        self._refresh_all()
        table = self._get_active_table()
        if table:
            table.focus()

    @on(Input.Changed, "#search-bar")
    def on_search_changed(self, event: Input.Changed) -> None:
        self.store.search_query = event.value.strip()
        self._refresh_all()

    # ── Actions (generic — delegated to handlers) ─────────────────────────

    def action_switch_view(self) -> None:
        if self._view_mode == "timeline":
            self._view_mode = "project"
            self.query_one("#timeline-view").add_class("hidden")
            self.query_one("#project-view").remove_class("hidden")
            if not self._selected_project:
                self._selected_project = "GLOBAL"
                self._selected_project_path = ""
        else:
            self._view_mode = "timeline"
            self.query_one("#project-view").add_class("hidden")
            self.query_one("#timeline-view").remove_class("hidden")
        self._refresh_all()
        self.call_after_refresh(self._focus_active_table)

    def action_view_item(self) -> None:
        handler, item = self._get_active_item()
        if not handler or not item:
            return
        info = handler.view_info(item, self.store)
        if not info:
            return
        header, content, session = info
        project_path = session.project_path if session else self._selected_project_path
        self.push_screen(
            ContentViewScreen(
                header, content, session=session, project_path=project_path
            )
        )

    def action_delete_item(self) -> None:
        handler, item = self._get_active_item()
        if not handler or not item:
            return
        info = handler.delete_info(item, self.store)
        if not info:
            if self._active_tab in ("skills", "rules"):
                self.notify("Cannot delete global item from here", severity="warning")
            return
        message, delete_fn = info

        def on_confirm(confirmed: bool) -> None:
            if confirmed and delete_fn():
                self._refresh_all()
                self.notify("Deleted")

        self.push_screen(ConfirmDialog(message), callback=on_confirm)

    def action_toggle_archive(self) -> None:
        handler, item = self._get_active_item()
        if not handler or not item or not handler.supports_archive:
            return
        msg = handler.toggle_archive(item, self.store)
        if msg:
            self._refresh_all()
            self.notify(msg)

    def action_toggle_show_archived(self) -> None:
        self.store.show_archived = not self.store.show_archived
        self._refresh_all()

    def action_rename(self) -> None:
        handler, item = self._get_active_item()
        if not handler or not item:
            return
        info = handler.rename_info(item, self.store)
        if not info:
            return
        dialog_title, current, apply_fn = info

        def on_name(name: str | None) -> None:
            if name:
                apply_fn(name)
                self._refresh_all()

        self.push_screen(InputDialog(dialog_title, default=current), callback=on_name)

    def action_new_item(self) -> None:
        handler = self._get_active_handler()
        if not handler:
            return
        label = handler.create_label()
        if not label:
            self.notify("Switch to Plans or Notes tab first", severity="warning")
            return
        pp = self._selected_project_path
        if not pp:
            self.notify("No project selected", severity="warning")
            return

        def on_title(t: str | None) -> None:
            if not t:
                return
            notify_msg, editor_path = handler.do_create(pp, t)
            self._refresh_all()
            if notify_msg:
                self.notify(notify_msg)
            if editor_path:
                editor = os.environ.get("EDITOR", "vim")
                self.suspend()
                subprocess.call([editor, str(editor_path)])
                self.resume()
                self._refresh_all()

        self.push_screen(
            InputDialog(f"New {label} title:", f"my-{label}"), callback=on_title
        )

    def action_edit_external(self) -> None:
        editor = os.environ.get("EDITOR", "vim")
        path: Path | None = None

        handler, item = self._get_active_item()
        if handler and item:
            path = handler.edit_path(item)
        elif self._active_tab == "config":
            pp = self._selected_project_path
            if pp:
                for candidate in [
                    Path(pp) / "CLAUDE.md",
                    Path(pp) / ".claude" / "CLAUDE.md",
                ]:
                    if candidate.exists():
                        path = candidate
                        break

        if not path:
            self.notify("Nothing to edit", severity="warning")
            return
        self.suspend()
        subprocess.call([editor, str(path)])
        self.resume()
        self._refresh_all()

    def action_export_session(self) -> None:
        handler, item = self._get_active_item()
        if not handler or not item:
            self.notify("Select a session first", severity="warning")
            return
        export = handler.get_export_content(item, self.store)
        if not export:
            self.notify("Select a session first", severity="warning")
            return
        default_title, content = export
        pp = getattr(item, "project_path", "") or self._selected_project_path
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

            self.push_screen(
                InputDialog("Title:", default=default_title), callback=on_title
            )

        self.push_screen(
            InputDialog("Export as (plan/note):", "plan"), callback=on_kind
        )

    def action_search(self) -> None:
        search_bar = self.query_one("#search-bar", Input)
        search_bar.display = True
        search_bar.value = self.store.search_query
        search_bar.focus()

    # ── Tab switching ─────────────────────────────────────────────────────

    def _goto_tab(self, index: int) -> None:
        if self._view_mode == "project" and 0 <= index < len(self._TAB_ORDER):
            self.query_one("#project-tabs", TabbedContent).active = self._TAB_ORDER[
                index
            ]

    def action_tab_next(self) -> None:
        if self._view_mode != "project":
            return
        tabs = self.query_one("#project-tabs", TabbedContent)
        idx = self._TAB_ORDER.index(tabs.active)
        tabs.active = self._TAB_ORDER[(idx + 1) % len(self._TAB_ORDER)]

    def action_tab_prev(self) -> None:
        if self._view_mode != "project":
            return
        tabs = self.query_one("#project-tabs", TabbedContent)
        idx = self._TAB_ORDER.index(tabs.active)
        tabs.active = self._TAB_ORDER[(idx - 1) % len(self._TAB_ORDER)]

    def action_goto_tab_1(self) -> None:
        self._goto_tab(0)

    def action_goto_tab_2(self) -> None:
        self._goto_tab(1)

    def action_goto_tab_3(self) -> None:
        self._goto_tab(2)

    def action_goto_tab_4(self) -> None:
        self._goto_tab(3)

    def action_goto_tab_5(self) -> None:
        self._goto_tab(4)

    def action_goto_tab_6(self) -> None:
        self._goto_tab(5)

    # ── Vim navigation ────────────────────────────────────────────────────

    def action_vim_down(self) -> None:
        table = self._get_active_table()
        if table and table.row_count > 0:
            table.move_cursor(row=min(table.cursor_row + 1, table.row_count - 1))

    def action_vim_up(self) -> None:
        table = self._get_active_table()
        if table and table.row_count > 0:
            table.move_cursor(row=max(table.cursor_row - 1, 0))

    def action_scroll_top(self) -> None:
        table = self._get_active_table()
        if table and table.row_count > 0:
            table.move_cursor(row=0)

    def action_scroll_bottom(self) -> None:
        table = self._get_active_table()
        if table and table.row_count > 0:
            table.move_cursor(row=table.row_count - 1)


def main() -> None:
    app = CcuiApp()
    app.run()


if __name__ == "__main__":
    main()
