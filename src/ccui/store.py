"""Central data store — single source of truth for all app state."""

from __future__ import annotations

import json

from ccui.archive import get_archived_ids
from ccui.constants import CLAUDE_DIR
from ccui.data import SessionInfo, get_project_names, load_all_sessions

SUMMARIES_FILE = CLAUDE_DIR / "ccui-summaries.json"
NOTE_SUMMARIES_FILE = CLAUDE_DIR / "ccui-note-summaries.json"


def _load_summaries() -> dict[str, str]:
    try:
        data = json.loads(SUMMARIES_FILE.read_text())
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _load_note_summaries() -> dict[str, str]:
    try:
        data = json.loads(NOTE_SUMMARIES_FILE.read_text())
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


class AppStore:
    def __init__(self) -> None:
        self.sessions: list[SessionInfo] = []
        self.archived_ids: set[str] = set()
        self.summaries: dict[str, str] = {}
        self.note_summaries: dict[str, str] = {}  # file path -> summary
        # View state
        self.show_archived: bool = False
        self.search_query: str = ""

    def reload(self) -> None:
        self.sessions = load_all_sessions()
        self.archived_ids = get_archived_ids()
        self.summaries = _load_summaries()
        self.note_summaries = _load_note_summaries()

    def reload_archived(self) -> None:
        self.archived_ids = get_archived_ids()

    def display_title(self, s: SessionInfo) -> str:
        return s.custom_title or s.session_id[:8]

    def display_summary(self, s: SessionInfo) -> str:
        return self.summaries.get(s.session_id, "")

    def visible_sessions(self, project: str | None = None) -> list[SessionInfo]:
        sessions = self.sessions
        if not self.show_archived:
            sessions = [s for s in sessions if s.session_id not in self.archived_ids]
        if project and project != "GLOBAL":
            sessions = [s for s in sessions if s.project_name == project]
        if self.search_query:
            q = self.search_query.lower()
            sessions = [
                s
                for s in sessions
                if q in self.display_title(s).lower()
                or q in self.display_summary(s).lower()
                or q in s.project_name.lower()
            ]
        return sessions

    def remove_session(self, session_id: str) -> None:
        self.sessions = [s for s in self.sessions if s.session_id != session_id]

    @property
    def project_names(self) -> list[str]:
        return get_project_names(self.sessions)
