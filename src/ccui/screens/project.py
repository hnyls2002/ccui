"""ProjectScreen — project-grouped view with tabbed content."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    DataTable,
    Header,
    OptionList,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from ccui.config import get_global_config, get_project_config
from ccui.screens.base import ItemListScreen
from ccui.screens.dialogs import InputDialog
from ccui.tabs import NotesTab, RulesTab, SessionsTab, SkillsTab
from ccui.tabs.base import TabHandler


class ProjectScreen(ItemListScreen):

    _KEY_MAP = {
        **ItemListScreen._KEY_MAP,
        "d": "_action_delete_item",
        "a": "_action_toggle_archive",
        "H": "_action_toggle_show_archived",
        "r": "_action_rename",
        "n": "_action_new_item",
        "e": "_action_edit_external",
        "x": "_action_export_item",
        "h": "_action_tab_prev",
        "l": "_action_tab_next",
        "1": "_action_goto_tab_1",
        "2": "_action_goto_tab_2",
        "3": "_action_goto_tab_3",
        "4": "_action_goto_tab_4",
        "5": "_action_goto_tab_5",
        "6": "_action_goto_tab_6",
    }

    _TAB_ORDER = [
        "tab-sessions",
        "tab-plans",
        "tab-notes",
        "tab-skills",
        "tab-rules",
        "tab-config",
    ]

    def __init__(self) -> None:
        super().__init__()
        self._selected_project: str = "GLOBAL"
        self._selected_project_path: str = ""
        self._active_tab = "sessions"
        self._project_tabs: dict[str, TabHandler] = {
            "sessions": SessionsTab(),
            "plans": NotesTab("plan"),
            "notes": NotesTab("note"),
            "skills": SkillsTab(),
            "rules": RulesTab(),
        }

    # ── Compose ───────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        yield from self._compose_search_bar()
        with Horizontal(id="project-view"):
            yield OptionList(id="project-list")
            with Vertical(id="right-panel"):
                with TabbedContent(id="project-tabs"):
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
                    with TabPane("Config", id="tab-config"):
                        yield Static("", id="config-content")
        yield from self._compose_footer()

    # ── Abstract implementations ──────────────────────────────────────

    def _setup_tables(self) -> None:
        for handler in self._project_tabs.values():
            table = self.query_one(f"#{handler.table_id}", DataTable)
            table.clear(columns=True)
            handler.setup_columns(table)

    def _get_active_handler(self) -> TabHandler | None:
        return self._project_tabs.get(self._active_tab)

    def _get_active_table(self) -> DataTable | None:
        handler = self._get_active_handler()
        if handler:
            return self.query_one(f"#{handler.table_id}", DataTable)
        return None

    def _do_refresh(self) -> None:
        self._refreshing = True
        self._refresh_project_list()
        project = self._selected_project
        project_path = self._selected_project_path
        for handler in self._project_tabs.values():
            table = self.query_one(f"#{handler.table_id}", DataTable)
            handler.refresh(table, self.store, project, project_path)
        self._refresh_config_panel()
        self._refreshing = False

    def _update_status(self) -> None:
        total = len(self.store.sessions)
        archived = sum(
            1 for s in self.store.sessions if s.session_id in self.store.archived_ids
        )
        table = self._get_active_table()
        visible = table.row_count if table else 0
        show_a = " | +archived" if self.store.show_archived else ""
        tab = f" | {self._active_tab}"
        status = (
            f" [Project:{self._selected_project}]"
            f" {visible}/{total} sessions | {archived} archived{show_a}{tab}"
        )
        if self.store.search_query:
            status += f" | /{self.store.search_query}"
        self.query_one("#status-bar", Static).update(status)
        self.query_one("#help-bar", Static).update(
            " q:Quit  Tab:View  h/l:Tab  1-6:Tab#  Enter:Open"
            "  d:Del  a:Archive  H:Hidden  r:Rename  n:New  e:Edit  x:Export  /:Search"
        )

    # ── Override: project path resolution ─────────────────────────────

    def _resolve_project_path(self, item: object, session: object | None = None) -> str:
        path = super()._resolve_project_path(item, session)
        return path or self._selected_project_path

    # ── Override: delete with notification for global items ───────────

    def _action_delete_item(self) -> None:
        handler, item = self._get_active_item()
        if not handler or not item:
            return
        info = handler.delete_info(item, self.store)
        if not info:
            if self._active_tab in ("skills", "rules"):
                self.notify("Cannot delete global item from here", severity="warning")
            return
        self._confirm_and_delete(*info)

    # ── Override: edit with config tab CLAUDE.md fallback ─────────────

    def _action_edit_external(self) -> None:
        handler, item = self._get_active_item()
        path = handler.edit_path(item) if handler and item else None
        if not path and self._active_tab == "config":
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
        self._open_in_editor(path)

    # ── Project-only: new item ────────────────────────────────────────

    def _action_new_item(self) -> None:
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
                self.app.suspend()
                subprocess.call([editor, str(editor_path)])
                self.app.resume()
                self._refresh_all()

        self.app.push_screen(
            InputDialog(f"New {label} title:", f"my-{label}"), callback=on_title
        )

    # ── Project list ──────────────────────────────────────────────────

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

    # ── Event handlers ────────────────────────────────────────────────

    @on(OptionList.OptionHighlighted, "#project-list")
    def _on_project_changed(self, event: OptionList.OptionHighlighted) -> None:
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
        self._refresh_all()

    @on(TabbedContent.TabActivated, "#project-tabs")
    def _on_tab_changed(self, event: TabbedContent.TabActivated) -> None:
        tab_id = str(event.pane.id) if event.pane else ""
        mapping = {h.tab_id: key for key, h in self._project_tabs.items()}
        mapping["tab-config"] = "config"
        self._active_tab = mapping.get(tab_id, "sessions")
        self._update_status()

    # ── Tab switching ─────────────────────────────────────────────────

    def _goto_tab(self, index: int) -> None:
        if 0 <= index < len(self._TAB_ORDER):
            self.query_one("#project-tabs", TabbedContent).active = self._TAB_ORDER[
                index
            ]

    def _action_tab_next(self) -> None:
        tabs = self.query_one("#project-tabs", TabbedContent)
        idx = self._TAB_ORDER.index(tabs.active)
        tabs.active = self._TAB_ORDER[(idx + 1) % len(self._TAB_ORDER)]

    def _action_tab_prev(self) -> None:
        tabs = self.query_one("#project-tabs", TabbedContent)
        idx = self._TAB_ORDER.index(tabs.active)
        tabs.active = self._TAB_ORDER[(idx - 1) % len(self._TAB_ORDER)]

    def _action_goto_tab_1(self) -> None:
        self._goto_tab(0)

    def _action_goto_tab_2(self) -> None:
        self._goto_tab(1)

    def _action_goto_tab_3(self) -> None:
        self._goto_tab(2)

    def _action_goto_tab_4(self) -> None:
        self._goto_tab(3)

    def _action_goto_tab_5(self) -> None:
        self._goto_tab(4)

    def _action_goto_tab_6(self) -> None:
        self._goto_tab(5)
