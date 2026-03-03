"""Rules tab handler."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.widgets import DataTable

from ccui.config import (
    RuleInfo,
    delete_rule,
    get_global_config,
    get_project_config,
    read_file_content,
)
from ccui.tabs.base import TabHandler

if TYPE_CHECKING:
    from ccui.store import AppStore


class RulesTab(TabHandler):
    tab_id = "tab-rules"
    tab_label = "Rules"
    table_id = "pv-rule-table"

    def __init__(self) -> None:
        self._items: list[RuleInfo] = []

    def setup_columns(self, table: DataTable) -> None:
        table.add_columns("Name", "Scope", "Source")

    def refresh(
        self, table: DataTable, store: AppStore, project: str, project_path: str
    ) -> None:
        if project == "GLOBAL" or not project_path:
            self._items = list(get_global_config().rules)
        else:
            self._items = list(get_project_config(project_path).rules)
        table.clear()
        for i, r in enumerate(self._items):
            scope = ", ".join(r.paths) if r.paths else "(all)"
            source = "global" if r.is_global else "project"
            table.add_row(r.name, scope, source, key=f"rule-{i}")

    def get_selected(self, table: DataTable) -> RuleInfo | None:
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        idx = int(row_key.value.split("-")[1])
        if 0 <= idx < len(self._items):
            return self._items[idx]
        return None

    def view_info(self, item: Any, store: AppStore) -> tuple[str, str, None] | None:
        rule: RuleInfo = item
        content = read_file_content(rule.path)
        source = "global" if rule.is_global else "project"
        header = f" RULE: {rule.name} ({source})"
        return header, content, None

    def delete_info(self, item: Any, store: AppStore) -> tuple[str, callable] | None:
        rule: RuleInfo = item
        if rule.is_global:
            return None
        return f"Delete rule '{rule.name}'?", lambda: delete_rule(rule)

    def edit_path(self, item: Any) -> Path | None:
        return item.path
