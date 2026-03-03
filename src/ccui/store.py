"""Central data store — single source of truth for all app state."""

from __future__ import annotations

from ccui.archive import get_archived_ids
from ccui.data import SessionInfo, get_project_names, load_all_sessions
from ccui.titles import get_all_titles, set_title


class AppStore:
    def __init__(self) -> None:
        self.sessions: list[SessionInfo] = []
        self.archived_ids: set[str] = set()
        self.custom_titles: dict[str, str] = {}
        # View state
        self.show_archived: bool = False
        self.search_query: str = ""

    def reload(self) -> None:
        self.sessions = load_all_sessions()
        self.archived_ids = get_archived_ids()
        self.custom_titles = get_all_titles()

    def reload_archived(self) -> None:
        self.archived_ids = get_archived_ids()

    def reload_titles(self) -> None:
        self.custom_titles = get_all_titles()

    def display_title(self, s: SessionInfo) -> str:
        return self.custom_titles.get(s.session_id, s.first_prompt[:60])

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
                or q in s.project_name.lower()
                or q in s.git_branch.lower()
            ]
        return sessions

    def remove_session(self, session_id: str) -> None:
        self.sessions = [s for s in self.sessions if s.session_id != session_id]

    def rename_session(self, session_id: str, title: str) -> None:
        set_title(session_id, title)
        self.reload_titles()

    @property
    def project_names(self) -> list[str]:
        return get_project_names(self.sessions)
