"""Skills tab handler."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.widgets import DataTable

from ccui.config import (
    SkillInfo,
    delete_skill,
    get_global_config,
    get_project_config,
    read_file_content,
)
from ccui.tabs.base import TabHandler

if TYPE_CHECKING:
    from ccui.store import AppStore


class SkillsTab(TabHandler):
    tab_id = "tab-skills"
    tab_label = "Skills"
    table_id = "pv-skill-table"

    def __init__(self) -> None:
        self._items: list[SkillInfo] = []

    def setup_columns(self, table: DataTable) -> None:
        table.add_columns("Name", "Description", "Source")

    def refresh(
        self, table: DataTable, store: AppStore, project: str, project_path: str
    ) -> None:
        if project == "GLOBAL" or not project_path:
            self._items = list(get_global_config().skills)
        else:
            self._items = list(get_project_config(project_path).skills)
        table.clear()
        for i, s in enumerate(self._items):
            source = "global" if s.is_global else "project"
            table.add_row(s.name, s.description, source, key=f"skill-{i}")

    def get_selected(self, table: DataTable) -> SkillInfo | None:
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        idx = int(row_key.value.split("-")[1])
        if 0 <= idx < len(self._items):
            return self._items[idx]
        return None

    def view_info(self, item: Any, store: AppStore) -> tuple[str, str, None] | None:
        skill: SkillInfo = item
        content = read_file_content(skill.path)
        source = "global" if skill.is_global else "project"
        header = f" SKILL: {skill.name} ({source})"
        return header, content, None

    def delete_info(self, item: Any, store: AppStore) -> tuple[str, callable] | None:
        skill: SkillInfo = item
        if skill.is_global:
            return None  # signal: cannot delete
        return f"Delete skill '{skill.name}'?", lambda: delete_skill(skill)

    def edit_path(self, item: Any) -> Path | None:
        return item.path
