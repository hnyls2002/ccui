"""TabHandler — abstract base for project view tab handlers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from textual.widgets import DataTable

if TYPE_CHECKING:
    from ccui.store import AppStore


class TabHandler(ABC):
    """Each tab handler knows how to setup, refresh, select, and act on its items."""

    tab_id: str  # e.g. "tab-sessions"
    tab_label: str  # e.g. "Sessions"
    table_id: str  # e.g. "pv-session-table"
    has_preview: bool = False
    supports_archive: bool = False

    @abstractmethod
    def setup_columns(self, table: DataTable) -> None:
        """Add columns to the table."""

    @abstractmethod
    def refresh(
        self, table: DataTable, store: AppStore, project: str, project_path: str
    ) -> None:
        """Load data and populate the table."""

    @abstractmethod
    def get_selected(self, table: DataTable) -> Any | None:
        """Get the currently selected item from the table."""

    # -- Optional actions (return None = not supported) --

    def view_info(
        self, item: Any, store: AppStore
    ) -> tuple[str, str, Any | None] | None:
        """Return (header, content, session_or_none) for the viewer, or None."""
        return None

    def delete_info(
        self, item: Any, store: AppStore
    ) -> tuple[str, Callable[[], bool]] | None:
        """Return (confirm_message, delete_fn), or None."""
        return None

    def edit_path(self, item: Any) -> Path | None:
        """Return file path for $EDITOR, or None."""
        return None

    def rename_info(
        self, item: Any, store: AppStore
    ) -> tuple[str, str, Callable[[str], None]] | None:
        """Return (dialog_title, current_value, apply_fn), or None."""
        return None

    def create_label(self) -> str | None:
        """Return kind label for creation dialog (e.g. 'plan'), or None."""
        return None

    def do_create(
        self, project_path: str, title: str
    ) -> tuple[str | None, Path | None]:
        """Create item. Return (notify_msg, editor_path_or_none)."""
        return None, None

    def toggle_archive(self, item: Any, store: AppStore) -> str | None:
        """Toggle archive state. Return notification text, or None."""
        return None

    def get_preview(self, item: Any, store: AppStore) -> str:
        """Return preview text for the item."""
        return ""

    def get_export_content(self, item: Any, store: AppStore) -> tuple[str, str] | None:
        """Return (default_title, formatted_content) for export, or None."""
        return None
