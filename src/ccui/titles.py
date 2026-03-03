"""Session title management — custom titles stored in ~/.claude/session-titles.json."""

from __future__ import annotations

import json
from pathlib import Path

TITLES_FILE = Path.home() / ".claude" / "session-titles.json"


def _load() -> dict[str, str]:
    if not TITLES_FILE.exists():
        return {}
    try:
        data = json.loads(TITLES_FILE.read_text())
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save(titles: dict[str, str]) -> None:
    TITLES_FILE.write_text(json.dumps(titles, indent=2, ensure_ascii=False) + "\n")


def get_title(session_id: str) -> str | None:
    """Get custom title for a session, or None if not set."""
    return _load().get(session_id)


def set_title(session_id: str, title: str) -> None:
    """Set a custom title for a session."""
    titles = _load()
    titles[session_id] = title
    _save(titles)


def delete_title(session_id: str) -> None:
    """Remove custom title for a session."""
    titles = _load()
    titles.pop(session_id, None)
    _save(titles)


def get_all_titles() -> dict[str, str]:
    """Get all custom titles."""
    return _load()
