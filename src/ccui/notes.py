"""Plan and Note CRUD — stored in {project}/.claude/plans/ and .claude/notes/."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass
class NoteInfo:
    title: str
    created: str  # date string
    session_id: str  # linked session id, "" if none
    path: Path
    kind: str  # "plan" or "note"

    @property
    def filename(self) -> str:
        return self.path.name


def _parse_frontmatter(path: Path) -> dict[str, str]:
    """Parse YAML-like frontmatter from a markdown file."""
    try:
        text = path.read_text()
    except OSError:
        return {}

    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}

    fm: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^(\w+)\s*:\s*(.+)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return fm


def _slugify(title: str) -> str:
    """Convert title to a filename-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:60] or "untitled"


def scan_notes(project_path: str, kind: str) -> list[NoteInfo]:
    """Scan {project}/.claude/plans/ or .claude/notes/ for markdown files."""
    subdir = "plans" if kind == "plan" else "notes"
    notes_dir = Path(project_path) / ".claude" / subdir
    if not notes_dir.exists():
        return []

    results: list[NoteInfo] = []
    for md_file in sorted(notes_dir.glob("*.md")):
        fm = _parse_frontmatter(md_file)
        results.append(
            NoteInfo(
                title=fm.get("title", md_file.stem),
                created=fm.get("created", ""),
                session_id=fm.get("session", ""),
                path=md_file,
                kind=kind,
            )
        )
    return results


def read_note(note: NoteInfo) -> str:
    """Read full content of a note/plan."""
    try:
        return note.path.read_text()
    except OSError:
        return "(failed to read)"


def create_note(
    project_path: str,
    kind: str,
    title: str,
    session_id: str = "",
    body: str = "",
) -> NoteInfo:
    """Create a new plan or note with frontmatter."""
    subdir = "plans" if kind == "plan" else "notes"
    notes_dir = Path(project_path) / ".claude" / subdir
    notes_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(title)
    path = notes_dir / f"{slug}.md"

    # Avoid name collision
    counter = 1
    while path.exists():
        path = notes_dir / f"{slug}-{counter}.md"
        counter += 1

    today = date.today().isoformat()
    lines = ["---", f"title: {title}", f"created: {today}"]
    if session_id:
        lines.append(f"session: {session_id}")
    lines.append("---")
    lines.append("")
    if body:
        lines.append(body)
    else:
        lines.append(f"# {title}")
        lines.append("")

    path.write_text("\n".join(lines) + "\n")

    return NoteInfo(
        title=title,
        created=today,
        session_id=session_id,
        path=path,
        kind=kind,
    )


def delete_note(note: NoteInfo) -> bool:
    """Delete a note/plan file."""
    try:
        if note.path.exists():
            note.path.unlink()
        return True
    except OSError:
        return False


def rename_note(note: NoteInfo, new_title: str) -> None:
    """Update the title in a note's frontmatter."""
    try:
        text = note.path.read_text()
    except OSError:
        return

    # Replace title in frontmatter
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("title:"):
            lines[i] = f"title: {new_title}"
            break

    note.path.write_text("\n".join(lines))
    note.title = new_title
