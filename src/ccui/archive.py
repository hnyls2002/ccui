"""Archive management — stores a list of archived session IDs in ~/.claude/session-archives.json."""

from __future__ import annotations

import json
from pathlib import Path

ARCHIVE_FILE = Path.home() / ".claude" / "session-archives.json"


def _load() -> set[str]:
    if not ARCHIVE_FILE.exists():
        return set()
    try:
        data = json.loads(ARCHIVE_FILE.read_text())
        if isinstance(data, list):
            return {x for x in data if isinstance(x, str)}
    except (json.JSONDecodeError, OSError):
        pass
    return set()


def _save(archived: set[str]) -> None:
    ARCHIVE_FILE.write_text(json.dumps(sorted(archived), indent=2) + "\n")


def is_archived(session_id: str) -> bool:
    return session_id in _load()


def toggle_archive(session_id: str) -> bool:
    """Toggle archive state. Returns new state (True = archived)."""
    archived = _load()
    if session_id in archived:
        archived.discard(session_id)
        _save(archived)
        return False
    else:
        archived.add(session_id)
        _save(archived)
        return True


def get_archived_ids() -> set[str]:
    return _load()
