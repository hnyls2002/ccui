"""Archive management — stores a list of archived session IDs in ~/.claude/session-archives.json."""

from __future__ import annotations

import json
from pathlib import Path

ARCHIVE_FILE = Path.home() / ".claude" / "session-archives.json"


def _load_dict() -> dict:
    """Load raw archive dict. Auto-migrates legacy array-of-SID format to dict."""
    if not ARCHIVE_FILE.exists():
        return {}
    try:
        data = json.loads(ARCHIVE_FILE.read_text())
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return {x: {} for x in data if isinstance(x, str)}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _load() -> set[str]:
    return {k for k in _load_dict() if isinstance(k, str)}


def _save(archived: set[str]) -> None:
    """Save archived set as dict. Preserves existing per-SID metadata (e.g. summary)
    for SIDs that remain archived; adds new SIDs as empty entries `{}`."""
    existing = _load_dict()
    new = {sid: existing.get(sid, {}) for sid in archived}
    ARCHIVE_FILE.write_text(json.dumps(new, indent=2, sort_keys=True) + "\n")


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
