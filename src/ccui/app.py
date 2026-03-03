"""ccui — Claude Code TUI Manager built with textual."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Header,
    Input,
    Label,
    OptionList,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)
from textual.widgets.option_list import Option

from ccui.archive import get_archived_ids, toggle_archive
from ccui.config import get_global_config, get_project_config
from ccui.data import (
    SessionInfo,
    delete_session,
    get_project_names,
    load_all_sessions,
    load_session_messages,
)
from ccui.notes import (
    NoteInfo,
    create_note,
    delete_note,
    read_note,
    rename_note,
    scan_notes,
)
from ccui.titles import get_all_titles, get_title, set_title

# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------


class ConfirmDialog(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
    ]
    DEFAULT_CSS = """
    ConfirmDialog { align: center middle; background: rgba(0, 0, 0, 0.6); }
    #confirm-box {
        width: 60;
        height: auto;
        max-height: 10;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }
    #confirm-msg { margin-bottom: 1; text-style: bold; }
    #confirm-hint { color: $text-muted; }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(self._message, id="confirm-msg")
            yield Label("  y = confirm  |  n / q / Esc = cancel", id="confirm-hint")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class InputDialog(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    InputDialog { align: center middle; }
    #input-box { width: 60; height: 9; border: thick $accent; background: $surface; padding: 1 2; }
    """

    def __init__(self, title: str, placeholder: str = "", default: str = "") -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="input-box"):
            yield Label(self._title)
            yield Input(
                placeholder=self._placeholder, value=self._default, id="dialog-input"
            )
            yield Label("[Enter] confirm / [Esc] cancel", classes="dim")

    @on(Input.Submitted, "#dialog-input")
    def on_submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Content viewer (session detail, note/plan, skill, rule, claude.md, etc.)
# ---------------------------------------------------------------------------


class ContentViewScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "back", "Back", priority=True),
        Binding("q", "back", "Back", priority=True),
        Binding("x", "export", "Export to plan/note", priority=True),
    ]
    DEFAULT_CSS = """
    ContentViewScreen { align: center middle; }
    #cv-box { width: 100%; height: 100%; border: thick $accent; background: $surface; }
    #cv-header { height: 3; padding: 0 2; background: $primary; color: $text; }
    #cv-content { height: 1fr; padding: 0 1; }
    """

    def __init__(
        self,
        header: str,
        content: str,
        session: SessionInfo | None = None,
        project_path: str = "",
    ) -> None:
        super().__init__()
        self._header = header
        self._content = content
        self._session = session
        self._project_path = project_path

    def compose(self) -> ComposeResult:
        with Vertical(id="cv-box"):
            yield Static(self._header, id="cv-header")
            yield TextArea(id="cv-content", read_only=True)

    def on_mount(self) -> None:
        self.query_one("#cv-content", TextArea).text = self._content

    def action_back(self) -> None:
        self.dismiss(None)

    def action_export(self) -> None:
        if not self._session or not self._project_path:
            self.notify("No session to export", severity="warning")
            return

        def on_kind(kind: str | None) -> None:
            if kind not in ("plan", "note"):
                return
            title = (
                get_title(self._session.session_id) or self._session.first_prompt[:60]
            )

            def on_title(t: str | None) -> None:
                if not t:
                    return
                create_note(
                    self._project_path, kind, t, self._session.session_id, self._content
                )
                self.notify(f"Exported as {kind}: {t}")

            self.app.push_screen(
                InputDialog("Title:", default=title), callback=on_title
            )

        self.app.push_screen(
            InputDialog("Export as (plan/note):", "plan"), callback=on_kind
        )


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------


class CcuiApp(App):
    TITLE = "ccui"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    #timeline-view { height: 1fr; }
    #project-view { height: 1fr; }
    #project-list { width: 25; height: 1fr; border-right: solid $accent; }
    #right-panel { width: 1fr; height: 1fr; }
    .session-table { height: 1fr; }
    .preview { height: 8; border-top: solid $accent; padding: 0 1; overflow-y: auto; }
    #status-bar { height: 1; padding: 0 1; background: $primary; color: $text; }
    #help-bar { height: 1; padding: 0 1; background: $surface; color: $text-muted; }
    #search-bar { height: 3; dock: top; display: none; }
    .hidden { display: none; }
    #config-content { padding: 1 2; height: 1fr; overflow-y: auto; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._sessions: list[SessionInfo] = []
        self._filtered: list[SessionInfo] = []
        self._archived_ids: set[str] = set()
        self._custom_titles: dict[str, str] = {}
        self._show_archived = False
        self._view_mode = "timeline"
        self._selected_project: str | None = None
        self._selected_project_path: str = ""
        self._search_query = ""
        self._active_tab = "sessions"
        self._refreshing = False  # guard against cascading refreshes
        # Notes/plans cache
        self._plans: list[NoteInfo] = []
        self._notes: list[NoteInfo] = []

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
                    with TabPane("Sessions", id="tab-sessions"):
                        yield DataTable(
                            id="pv-session-table",
                            cursor_type="row",
                            classes="session-table",
                        )
                        yield Static("", id="pv-preview", classes="preview")
                    with TabPane("Plans", id="tab-plans"):
                        yield DataTable(
                            id="pv-plan-table",
                            cursor_type="row",
                            classes="session-table",
                        )
                    with TabPane("Notes", id="tab-notes"):
                        yield DataTable(
                            id="pv-note-table",
                            cursor_type="row",
                            classes="session-table",
                        )
                    with TabPane("Config", id="tab-config"):
                        yield Static("", id="config-content")

        yield Static("", id="status-bar")
        yield Static("", id="help-bar")

    def on_mount(self) -> None:
        self._load_data()
        self._setup_all_tables()
        self._refresh_all()
        self.call_after_refresh(self._focus_active_table)

    def _focus_active_table(self) -> None:
        table = self._get_active_table()
        table.focus()
        if table.row_count > 0:
            table.move_cursor(row=0)

    # ── Data loading ─────────────────────────────────────────────────────

    def _load_data(self) -> None:
        self._sessions = load_all_sessions()
        self._archived_ids = get_archived_ids()
        self._custom_titles = get_all_titles()

    def _get_display_title(self, s: SessionInfo) -> str:
        return self._custom_titles.get(s.session_id, s.first_prompt[:60])

    def _load_notes_for_project(self) -> None:
        if self._selected_project_path:
            self._plans = scan_notes(self._selected_project_path, "plan")
            self._notes = scan_notes(self._selected_project_path, "note")
        else:
            self._plans = []
            self._notes = []

    # ── Table setup ──────────────────────────────────────────────────────

    def _setup_all_tables(self) -> None:
        tl = self.query_one("#tl-table", DataTable)
        tl.clear(columns=True)
        tl.add_columns("", "Project", "Title", "Msgs", "Date", "Branch")

        pv = self.query_one("#pv-session-table", DataTable)
        pv.clear(columns=True)
        pv.add_columns("", "Title", "Msgs", "Date", "Branch")

        pt = self.query_one("#pv-plan-table", DataTable)
        pt.clear(columns=True)
        pt.add_columns("Title", "Date", "Session")

        nt = self.query_one("#pv-note-table", DataTable)
        nt.clear(columns=True)
        nt.add_columns("Title", "Date", "Session")

    # ── Refresh ──────────────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        if self._view_mode == "timeline":
            self._refresh_timeline()
        else:
            self._refresh_project_view()
        self._update_status()

    def _get_visible_sessions(
        self, project_filter: str | None = None
    ) -> list[SessionInfo]:
        sessions = self._sessions
        if not self._show_archived:
            sessions = [s for s in sessions if s.session_id not in self._archived_ids]
        if project_filter:
            sessions = [s for s in sessions if s.project_name == project_filter]
        if self._search_query:
            q = self._search_query.lower()
            sessions = [
                s
                for s in sessions
                if q in self._get_display_title(s).lower()
                or q in s.project_name.lower()
                or q in s.git_branch.lower()
            ]
        return sessions

    def _refresh_timeline(self) -> None:
        self._refreshing = True
        self._filtered = self._get_visible_sessions()
        table = self.query_one("#tl-table", DataTable)
        table.clear()
        for s in self._filtered:
            archived = "[A]" if s.session_id in self._archived_ids else ""
            table.add_row(
                archived,
                s.project_name,
                self._get_display_title(s),
                str(s.message_count),
                s.date_str,
                s.git_branch,
                key=s.session_id,
            )
        self._refreshing = False

    def _refresh_project_view(self) -> None:
        self._refreshing = True
        # Project list
        project_list = self.query_one("#project-list", OptionList)
        prev = project_list.highlighted
        project_list.clear_options()
        names = get_project_names(self._sessions)
        for name in names:
            count = sum(1 for s in self._sessions if s.project_name == name)
            project_list.add_option(Option(f"{name} ({count})"))
        if prev is not None and prev < len(names):
            project_list.highlighted = prev

        # Sessions
        self._filtered = self._get_visible_sessions(self._selected_project)
        table = self.query_one("#pv-session-table", DataTable)
        table.clear()
        for s in self._filtered:
            archived = "[A]" if s.session_id in self._archived_ids else ""
            table.add_row(
                archived,
                self._get_display_title(s),
                str(s.message_count),
                s.date_str,
                s.git_branch,
                key=s.session_id,
            )

        # Plans & Notes
        self._load_notes_for_project()
        pt = self.query_one("#pv-plan-table", DataTable)
        pt.clear()
        for p in self._plans:
            linked = ""
            if p.session_id:
                linked = f"→ {self._custom_titles.get(p.session_id, p.session_id[:8])}"
            pt.add_row(p.title, p.created, linked, key=str(p.path))

        nt = self.query_one("#pv-note-table", DataTable)
        nt.clear()
        for n in self._notes:
            linked = ""
            if n.session_id:
                linked = f"→ {self._custom_titles.get(n.session_id, n.session_id[:8])}"
            nt.add_row(n.title, n.created, linked, key=str(n.path))

        # Config
        self._refresh_config_panel()
        self._refreshing = False

    def _refresh_config_panel(self) -> None:
        if not self._selected_project_path:
            self.query_one("#config-content", Static).update("(select a project)")
            return

        cfg = get_project_config(self._selected_project_path)
        gcfg = get_global_config()
        lines: list[str] = []

        # CLAUDE.md
        if cfg.claude_md_path:
            lines.append(f"CLAUDE.md         : found ({cfg.claude_md_lines} lines)")
        else:
            lines.append("CLAUDE.md         : not found")

        # Memory
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

        # Settings
        lines.append(f"settings.local    : {cfg.permission_count} permission rules")
        lines.append("")

        # Rules
        lines.append("Rules (project):")
        if cfg.rules:
            for r in cfg.rules:
                scope = f"paths: {', '.join(r.paths)}" if r.paths else "(global)"
                lines.append(f"  • {r.name} — {scope}")
        else:
            lines.append("  (none)")
        lines.append("")

        # Skills
        lines.append("Skills (project):")
        if cfg.skills:
            for s in cfg.skills:
                lines.append(f"  • {s.name} — {s.description}")
        else:
            lines.append("  (none)")
        lines.append("")

        lines.append("Skills (global):")
        for s in gcfg.skills:
            lines.append(f"  • {s.name} — {s.description}")
        if not gcfg.skills:
            lines.append("  (none)")

        # Global CLAUDE.md
        lines.append("")
        if gcfg.claude_md_path:
            lines.append(f"Global CLAUDE.md  : found ({gcfg.claude_md_lines} lines)")
        else:
            lines.append("Global CLAUDE.md  : not found")
        lines.append(f"Global settings   : {gcfg.permission_count} permission rules")

        self.query_one("#config-content", Static).update("\n".join(lines))

    def _update_status(self) -> None:
        total = len(self._sessions)
        archived = sum(1 for s in self._sessions if s.session_id in self._archived_ids)
        visible = len(self._filtered)
        view = (
            "Timeline"
            if self._view_mode == "timeline"
            else f"Project:{self._selected_project or '?'}"
        )
        show_a = " | +archived" if self._show_archived else ""
        tab = f" | {self._active_tab}" if self._view_mode == "project" else ""

        status = (
            f" [{view}] {visible}/{total} sessions | {archived} archived{show_a}{tab}"
        )
        if self._search_query:
            status += f" | /{self._search_query}"
        self.query_one("#status-bar", Static).update(status)

        help_text = " q:Quit  Tab:View  h/l:Tab  d:Del  a:Archive  H:Hidden  r:Rename  n:New  e:Edit  x:Export  /:Search"
        self.query_one("#help-bar", Static).update(help_text)

    # ── Selection helpers ────────────────────────────────────────────────

    def _get_active_table(self) -> DataTable:
        if self._view_mode == "timeline":
            return self.query_one("#tl-table", DataTable)
        if self._active_tab == "sessions":
            return self.query_one("#pv-session-table", DataTable)
        if self._active_tab == "plans":
            return self.query_one("#pv-plan-table", DataTable)
        if self._active_tab == "notes":
            return self.query_one("#pv-note-table", DataTable)
        return self.query_one("#tl-table", DataTable)

    def _get_selected_session(self) -> SessionInfo | None:
        if self._active_tab not in ("sessions",) and self._view_mode == "project":
            return None
        table = self._get_active_table()
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        sid = row_key.value
        for s in self._filtered:
            if s.session_id == sid:
                return s
        return None

    def _get_selected_note(self) -> NoteInfo | None:
        if self._active_tab == "plans":
            items = self._plans
            table = self.query_one("#pv-plan-table", DataTable)
        elif self._active_tab == "notes":
            items = self._notes
            table = self.query_one("#pv-note-table", DataTable)
        else:
            return None
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        path_str = row_key.value
        for item in items:
            if str(item.path) == path_str:
                return item
        return None

    def _update_preview(self) -> None:
        if self._view_mode == "timeline":
            preview = self.query_one("#tl-preview", Static)
        elif self._active_tab == "sessions":
            preview = self.query_one("#pv-preview", Static)
        else:
            return

        session = self._get_selected_session()
        if not session:
            preview.update("")
            return
        messages = load_session_messages(session.jsonl_path, max_messages=4)
        lines: list[str] = []
        for msg in messages:
            role = "USER" if msg["role"] == "user" else "ASST"
            text = msg["text"].replace("\n", " ")[:100]
            lines.append(f"  {role}: {text}")
        preview.update("\n".join(lines) if lines else "  (no messages)")

    def _resolve_project_path(self) -> str:
        """Get the project path for the current context."""
        if self._selected_project_path:
            return self._selected_project_path
        session = self._get_selected_session()
        if session:
            return session.project_path
        return ""

    # ── Key dispatch ─────────────────────────────────────────────────────

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
        "1": "action_tab_sessions",
        "2": "action_tab_plans",
        "3": "action_tab_notes",
        "4": "action_tab_config",
        "j": "action_vim_down",
        "k": "action_vim_up",
        "g": "action_scroll_top",
        "G": "action_scroll_bottom",
        "down": "action_vim_down",
        "up": "action_vim_up",
    }

    def on_key(self, event) -> None:
        # Don't intercept keys when search bar is active
        search_bar = self.query_one("#search-bar", Input)
        if search_bar.display and search_bar.has_focus:
            if event.key == "escape":
                search_bar.display = False
                self._search_query = ""
                self._refresh_all()
                self._get_active_table().focus()
                event.prevent_default()
                event.stop()
            return

        action = self._KEY_MAP.get(event.key)
        if action:
            getattr(self, action)()
            event.prevent_default()
            event.stop()

    # ── Event handlers ───────────────────────────────────────────────────

    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._refreshing:
            return
        # Only respond to the currently active table
        active_ids = {
            ("timeline", "sessions"): "tl-table",
            ("project", "sessions"): "pv-session-table",
            ("project", "plans"): "pv-plan-table",
            ("project", "notes"): "pv-note-table",
        }
        expected_id = active_ids.get((self._view_mode, self._active_tab))
        if expected_id and event.data_table.id != expected_id:
            return
        self._update_preview()

    @on(OptionList.OptionHighlighted, "#project-list")
    def on_project_changed(self, event: OptionList.OptionHighlighted) -> None:
        if self._refreshing or event.option is None:
            return
        text = str(event.option.prompt)
        name = text.rsplit(" (", 1)[0]
        if name == self._selected_project:
            return  # no change
        self._selected_project = name
        for s in self._sessions:
            if s.project_name == name:
                self._selected_project_path = s.project_path
                break
        self._refresh_project_view()
        self._update_status()

    @on(TabbedContent.TabActivated, "#project-tabs")
    def on_tab_changed(self, event: TabbedContent.TabActivated) -> None:
        tab_id = str(event.pane.id) if event.pane else ""
        mapping = {
            "tab-sessions": "sessions",
            "tab-plans": "plans",
            "tab-notes": "notes",
            "tab-config": "config",
        }
        self._active_tab = mapping.get(tab_id, "sessions")
        self._update_status()

    @on(Input.Submitted, "#search-bar")
    def on_search_submitted(self, event: Input.Submitted) -> None:
        self._search_query = event.value.strip()
        self.query_one("#search-bar", Input).display = False
        self._refresh_all()
        self._get_active_table().focus()

    @on(Input.Changed, "#search-bar")
    def on_search_changed(self, event: Input.Changed) -> None:
        self._search_query = event.value.strip()
        self._refresh_all()

    # ── Actions ──────────────────────────────────────────────────────────

    def action_switch_view(self) -> None:
        if self._view_mode == "timeline":
            self._view_mode = "project"
            self.query_one("#timeline-view").add_class("hidden")
            self.query_one("#project-view").remove_class("hidden")
            names = get_project_names(self._sessions)
            if names and not self._selected_project:
                self._selected_project = names[0]
                for s in self._sessions:
                    if s.project_name == names[0]:
                        self._selected_project_path = s.project_path
                        break
        else:
            self._view_mode = "timeline"
            self.query_one("#project-view").add_class("hidden")
            self.query_one("#timeline-view").remove_class("hidden")
        self._refresh_all()
        self.call_after_refresh(self._focus_active_table)

    def action_view_item(self) -> None:
        if self._active_tab in ("plans", "notes") and self._view_mode == "project":
            note = self._get_selected_note()
            if note:
                content = read_note(note)
                header = f" {note.kind.upper()}: {note.title}"
                self.push_screen(
                    ContentViewScreen(
                        header, content, project_path=self._selected_project_path
                    )
                )
            return

        if self._active_tab == "config" and self._view_mode == "project":
            return

        session = self._get_selected_session()
        if not session:
            return
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
        title = self._get_display_title(session)
        header = f" {session.project_name} | {title} | {session.message_count} msgs | {session.date_str}"
        self.push_screen(
            ContentViewScreen(
                header, content, session=session, project_path=session.project_path
            )
        )

    def action_delete_item(self) -> None:
        if self._active_tab in ("plans", "notes") and self._view_mode == "project":
            note = self._get_selected_note()
            if not note:
                return

            def on_confirm(confirmed: bool) -> None:
                if confirmed and delete_note(note):
                    self._refresh_project_view()
                    self.notify(f"Deleted {note.kind}: {note.title}")

            self.push_screen(
                ConfirmDialog(f"Delete {note.kind} '{note.title}'?"),
                callback=on_confirm,
            )
            return

        session = self._get_selected_session()
        if not session:
            return

        def on_confirm(confirmed: bool) -> None:
            if confirmed and delete_session(session):
                self._sessions = [
                    s for s in self._sessions if s.session_id != session.session_id
                ]
                self._refresh_all()
                self.notify(f"Deleted: {self._get_display_title(session)}")

        self.push_screen(
            ConfirmDialog(f"Delete session '{self._get_display_title(session)[:40]}'?"),
            callback=on_confirm,
        )

    def action_toggle_archive(self) -> None:
        session = self._get_selected_session()
        if not session:
            return
        new_state = toggle_archive(session.session_id)
        self._archived_ids = get_archived_ids()
        self._refresh_all()
        label = "Archived" if new_state else "Unarchived"
        self.notify(f"{label}: {self._get_display_title(session)[:40]}")

    def action_toggle_show_archived(self) -> None:
        self._show_archived = not self._show_archived
        self._refresh_all()

    def action_rename(self) -> None:
        if self._active_tab in ("plans", "notes") and self._view_mode == "project":
            note = self._get_selected_note()
            if not note:
                return

            def on_title(t: str | None) -> None:
                if t:
                    rename_note(note, t)
                    self._refresh_project_view()

            self.push_screen(
                InputDialog("Rename:", default=note.title), callback=on_title
            )
            return

        session = self._get_selected_session()
        if not session:
            return
        current = self._get_display_title(session)

        def on_title(t: str | None) -> None:
            if t:
                set_title(session.session_id, t)
                self._custom_titles = get_all_titles()
                self._refresh_all()

        self.push_screen(
            InputDialog("Rename session:", default=current), callback=on_title
        )

    def action_new_item(self) -> None:
        if self._view_mode != "project" or self._active_tab not in ("plans", "notes"):
            self.notify("Switch to Plans or Notes tab first", severity="warning")
            return
        kind = "plan" if self._active_tab == "plans" else "note"
        pp = self._resolve_project_path()
        if not pp:
            self.notify("No project selected", severity="warning")
            return

        def on_title(t: str | None) -> None:
            if not t:
                return
            note = create_note(pp, kind, t)
            self._refresh_project_view()
            self.notify(f"Created {kind}: {t}")
            # Open in $EDITOR
            editor = os.environ.get("EDITOR", "vim")
            self.app.suspend()
            subprocess.call([editor, str(note.path)])
            self.app.resume()

        self.push_screen(
            InputDialog(f"New {kind} title:", f"my-{kind}"), callback=on_title
        )

    def action_edit_external(self) -> None:
        editor = os.environ.get("EDITOR", "vim")
        path: Path | None = None

        if self._active_tab in ("plans", "notes") and self._view_mode == "project":
            note = self._get_selected_note()
            if note:
                path = note.path
        elif self._active_tab == "config":
            pp = self._resolve_project_path()
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
        if self._view_mode == "project":
            self._refresh_project_view()

    def action_export_session(self) -> None:
        session = self._get_selected_session()
        if not session:
            self.notify("Select a session first", severity="warning")
            return
        pp = session.project_path or self._resolve_project_path()
        if not pp:
            self.notify("No project path", severity="warning")
            return

        messages = load_session_messages(session.jsonl_path)
        lines: list[str] = []
        for msg in messages:
            role = "USER" if msg["role"] == "user" else "CLAUDE"
            lines.append(f"### {role}\n\n{msg['text']}\n")
        content = "\n".join(lines)

        def on_kind(kind: str | None) -> None:
            if kind not in ("plan", "note"):
                return
            title = self._get_display_title(session)

            def on_title(t: str | None) -> None:
                if not t:
                    return
                create_note(pp, kind, t, session.session_id, content)
                self._refresh_all()
                self.notify(f"Exported as {kind}: {t}")

            self.push_screen(InputDialog("Title:", default=title), callback=on_title)

        self.push_screen(
            InputDialog("Export as (plan/note):", "plan"), callback=on_kind
        )

    def action_search(self) -> None:
        search_bar = self.query_one("#search-bar", Input)
        search_bar.display = True
        search_bar.value = self._search_query
        search_bar.focus()

    # Tab switching
    _TAB_ORDER = ["tab-sessions", "tab-plans", "tab-notes", "tab-config"]

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

    def action_tab_sessions(self) -> None:
        if self._view_mode == "project":
            self.query_one("#project-tabs", TabbedContent).active = "tab-sessions"

    def action_tab_plans(self) -> None:
        if self._view_mode == "project":
            self.query_one("#project-tabs", TabbedContent).active = "tab-plans"

    def action_tab_notes(self) -> None:
        if self._view_mode == "project":
            self.query_one("#project-tabs", TabbedContent).active = "tab-notes"

    def action_tab_config(self) -> None:
        if self._view_mode == "project":
            self.query_one("#project-tabs", TabbedContent).active = "tab-config"

    # Vim navigation
    def action_vim_down(self) -> None:
        table = self._get_active_table()
        if table.row_count > 0:
            table.move_cursor(row=min(table.cursor_row + 1, table.row_count - 1))

    def action_vim_up(self) -> None:
        table = self._get_active_table()
        if table.row_count > 0:
            table.move_cursor(row=max(table.cursor_row - 1, 0))

    def action_scroll_top(self) -> None:
        table = self._get_active_table()
        if table.row_count > 0:
            table.move_cursor(row=0)

    def action_scroll_bottom(self) -> None:
        table = self._get_active_table()
        if table.row_count > 0:
            table.move_cursor(row=table.row_count - 1)


def main() -> None:
    app = CcuiApp()
    app.run()


if __name__ == "__main__":
    main()
