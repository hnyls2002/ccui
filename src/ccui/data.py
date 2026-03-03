"""Scan and parse Claude Code session data from ~/.claude/projects/."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"


@dataclass
class SessionInfo:
    session_id: str
    project_path: str  # original project path, e.g. /Users/x/common_sync/sglang
    project_name: str  # short name, e.g. sglang
    first_prompt: str
    message_count: int
    created: datetime | None
    modified: datetime | None
    git_branch: str
    jsonl_path: Path

    @property
    def date_str(self) -> str:
        dt = self.modified or self.created
        if dt is None:
            return "?"
        return dt.strftime("%b %d")

    @property
    def created_str(self) -> str:
        if self.created is None:
            return "?"
        return self.created.strftime("%Y-%m-%d %H:%M")

    @property
    def modified_str(self) -> str:
        if self.modified is None:
            return "?"
        return self.modified.strftime("%Y-%m-%d %H:%M")


def _project_name_from_path(project_path: str) -> str:
    """Extract a short project name from the full path."""
    if not project_path:
        return "~"
    parts = project_path.rstrip("/").split("/")
    # Use last component, fallback to ~ for home dir
    name = parts[-1] if parts else "~"
    return name or "~"


def _read_original_path(project_dir: Path) -> str:
    """Read originalPath from sessions-index.json if available."""
    index_file = project_dir / "sessions-index.json"
    if not index_file.exists():
        return ""
    try:
        data = json.loads(index_file.read_text())
        return data.get("originalPath", "")
    except (json.JSONDecodeError, OSError):
        return ""


def _dir_name_to_project_path(dir_name: str) -> str:
    """Convert a project directory name back to original path.

    Claude Code encodes paths by replacing both / and _ with -.
    We walk the filesystem greedily, trying to merge adjacent segments
    with _ or - when a direct / split doesn't match.
    """
    parts = dir_name.lstrip("-").split("-")
    current = "/"
    i = 0
    while i < len(parts):
        # Try single segment as a direct child
        candidate = os.path.join(current, parts[i])
        if os.path.exists(candidate):
            current = candidate
            i += 1
            continue
        # Try merging adjacent segments with _ or -
        found = False
        for j in range(i + 1, min(i + 4, len(parts) + 1)):
            for sep in ("_", "-", "."):
                merged = sep.join(parts[i : j + 1])
                candidate = os.path.join(current, merged)
                if os.path.exists(candidate):
                    current = candidate
                    i = j + 1
                    found = True
                    break
            if found:
                break
        if not found:
            # Fallback: use segment as-is even if path doesn't exist
            current = os.path.join(current, parts[i])
            i += 1
    return current


def _parse_iso_datetime(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _parse_timestamp(ts: int | float | str | None) -> datetime | None:
    """Parse a timestamp that could be ms-epoch (int/float) or ISO string."""
    if ts is None:
        return None
    if isinstance(ts, str):
        return _parse_iso_datetime(ts)
    try:
        return datetime.fromtimestamp(ts / 1000)
    except (ValueError, TypeError, OSError):
        return None


def _load_sessions_from_index(project_dir: Path) -> list[SessionInfo]:
    """Load sessions from sessions-index.json if available."""
    index_file = project_dir / "sessions-index.json"
    if not index_file.exists():
        return []

    try:
        data = json.loads(index_file.read_text())
    except (json.JSONDecodeError, OSError):
        return []

    original_path = data.get("originalPath", "")
    project_name = _project_name_from_path(original_path)
    sessions = []

    for entry in data.get("entries", []):
        sid = entry.get("sessionId", "")
        jsonl_path = project_dir / f"{sid}.jsonl"
        sessions.append(
            SessionInfo(
                session_id=sid,
                project_path=original_path,
                project_name=project_name,
                first_prompt=entry.get("firstPrompt", "No prompt"),
                message_count=entry.get("messageCount", 0),
                created=_parse_iso_datetime(entry.get("created")),
                modified=_parse_iso_datetime(entry.get("modified")),
                git_branch=entry.get("gitBranch", ""),
                jsonl_path=jsonl_path,
            )
        )

    return sessions


def _parse_session_from_jsonl(
    jsonl_path: Path, project_path: str
) -> SessionInfo | None:
    """Parse a session JSONL file to extract basic metadata."""
    sid = jsonl_path.stem
    project_name = _project_name_from_path(project_path)
    first_prompt = "No prompt"
    message_count = 0
    first_ts = None
    last_ts = None
    git_branch = ""

    try:
        with open(jsonl_path) as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = obj.get("type", "")
                ts = obj.get("timestamp")

                if msg_type in ("user", "assistant"):
                    message_count += 1
                    if ts:
                        if first_ts is None:
                            first_ts = ts
                        last_ts = ts

                    if not git_branch:
                        git_branch = obj.get("gitBranch", "")

                    # Extract first user prompt
                    if msg_type == "user" and first_prompt == "No prompt":
                        if "toolUseResult" not in obj:
                            msg = obj.get("message", {})
                            content = (
                                msg.get("content", "") if isinstance(msg, dict) else ""
                            )
                            if isinstance(content, str) and content.strip():
                                first_prompt = content.strip()[:200]
                            elif isinstance(content, list):
                                for item in content:
                                    if (
                                        isinstance(item, dict)
                                        and item.get("type") == "text"
                                    ):
                                        text = item.get("text", "").strip()
                                        if text:
                                            first_prompt = text[:200]
                                            break
    except OSError:
        return None

    if message_count == 0:
        return None

    return SessionInfo(
        session_id=sid,
        project_path=project_path,
        project_name=project_name,
        first_prompt=first_prompt,
        message_count=message_count,
        created=_parse_timestamp(first_ts),
        modified=_parse_timestamp(last_ts),
        git_branch=git_branch,
        jsonl_path=jsonl_path,
    )


def load_all_sessions() -> list[SessionInfo]:
    """Scan all projects and return session list sorted by modified time (newest first)."""
    if not PROJECTS_DIR.exists():
        return []

    sessions: list[SessionInfo] = []
    indexed_sids: set[str] = set()

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir() or project_dir.name.startswith("."):
            continue

        # Get project path: prefer originalPath from index, fallback to dir name
        project_path = _read_original_path(project_dir) or _dir_name_to_project_path(
            project_dir.name
        )

        # Try loading from index first
        indexed = _load_sessions_from_index(project_dir)
        for s in indexed:
            indexed_sids.add(s.session_id)
        sessions.extend(indexed)

        # Also scan JSONL files not in the index
        for jsonl_file in project_dir.glob("*.jsonl"):
            sid = jsonl_file.stem
            if sid in indexed_sids:
                continue
            parsed = _parse_session_from_jsonl(jsonl_file, project_path)
            if parsed:
                sessions.append(parsed)

    # Sort by modified time, newest first (strip tzinfo for comparison)
    def _sort_key(s: SessionInfo) -> datetime:
        dt = s.modified or s.created
        if dt is None:
            return datetime.min
        return dt.replace(tzinfo=None)

    sessions.sort(key=_sort_key, reverse=True)
    return sessions


def load_session_messages(jsonl_path: Path, max_messages: int = 0) -> list[dict]:
    """Load user/assistant text messages from a session JSONL file.

    Args:
        max_messages: If > 0, stop after collecting this many messages (for preview).

    Returns list of dicts: {"role": "user"|"assistant", "text": "..."}
    """
    messages: list[dict] = []
    if not jsonl_path.exists():
        return messages

    try:
        with open(jsonl_path) as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = obj.get("type", "")
                if msg_type not in ("user", "assistant"):
                    continue

                # Skip tool use results (auto-generated)
                if msg_type == "user" and "toolUseResult" in obj:
                    continue

                msg = obj.get("message", {})
                if not isinstance(msg, dict):
                    continue

                content = msg.get("content", "")
                text = ""
                if isinstance(content, str):
                    text = content.strip()
                elif isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                    text = "\n".join(text_parts).strip()

                if text:
                    messages.append({"role": msg_type, "text": text})
                    if max_messages and len(messages) >= max_messages:
                        return messages
    except OSError:
        pass

    return messages


def delete_session(session: SessionInfo) -> bool:
    """Delete a session's JSONL file. Returns True if successful."""
    try:
        if session.jsonl_path.exists():
            session.jsonl_path.unlink()

        # Also try to remove the companion directory (if exists, e.g. file snapshots)
        companion_dir = session.jsonl_path.with_suffix("")
        if companion_dir.is_dir():
            import shutil

            shutil.rmtree(companion_dir, ignore_errors=True)

        # Remove from sessions-index.json if present
        index_file = session.jsonl_path.parent / "sessions-index.json"
        if index_file.exists():
            try:
                data = json.loads(index_file.read_text())
                entries = data.get("entries", [])
                data["entries"] = [
                    e for e in entries if e.get("sessionId") != session.session_id
                ]
                index_file.write_text(json.dumps(data, indent=4))
            except (json.JSONDecodeError, OSError):
                pass

        return True
    except OSError:
        return False


def get_project_names(sessions: list[SessionInfo]) -> list[str]:
    """Get unique project names sorted alphabetically."""
    names = sorted({s.project_name for s in sessions})
    return names
