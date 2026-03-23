"""Tests for ccui.notes — slug, frontmatter, note CRUD."""

from __future__ import annotations

from pathlib import Path

from ccui.notes import (
    NoteInfo,
    _parse_frontmatter,
    _slugify,
    create_note,
    delete_note,
    read_note,
    rename_note,
    scan_notes,
)

# ── _slugify ─────────────────────────────────────────────────────────


class TestSlugify:
    def test_simple(self):
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars(self):
        assert _slugify("Fix bug #123!") == "fix-bug-123"

    def test_underscores(self):
        assert _slugify("my_var_name") == "my-var-name"

    def test_empty(self):
        assert _slugify("") == "untitled"

    def test_only_special(self):
        assert _slugify("!!!") == "untitled"

    def test_truncates_long(self):
        result = _slugify("a" * 100)
        assert len(result) <= 60

    def test_strips_leading_trailing_hyphens(self):
        assert _slugify("-hello-") == "hello"


# ── _parse_frontmatter ──────────────────────────────────────────────


class TestParseFrontmatter:
    def test_basic(self, tmp_path):
        p = tmp_path / "note.md"
        p.write_text("---\ntitle: My Note\ncreated: 2025-01-01\n---\n\nBody text\n")
        fm = _parse_frontmatter(p)
        assert fm["title"] == "My Note"
        assert fm["created"] == "2025-01-01"

    def test_no_frontmatter(self, tmp_path):
        p = tmp_path / "plain.md"
        p.write_text("# Just a heading\n\nBody text\n")
        assert _parse_frontmatter(p) == {}

    def test_missing_file(self, tmp_path):
        assert _parse_frontmatter(tmp_path / "nope.md") == {}

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.md"
        p.write_text("")
        assert _parse_frontmatter(p) == {}

    def test_with_session(self, tmp_path):
        p = tmp_path / "linked.md"
        p.write_text("---\ntitle: Linked\nsession: abc123\n---\n")
        fm = _parse_frontmatter(p)
        assert fm["session"] == "abc123"


# ── create_note ──────────────────────────────────────────────────────


class TestCreateNote:
    def test_creates_file(self, tmp_path):
        note = create_note(str(tmp_path), "plan", "My Plan")
        assert note.path.exists()
        assert note.title == "My Plan"
        assert note.kind == "plan"
        content = note.path.read_text()
        assert "title: My Plan" in content

    def test_creates_in_correct_subdir(self, tmp_path):
        note = create_note(str(tmp_path), "note", "My Note")
        assert ".claude/notes/" in str(note.path)

    def test_plan_subdir(self, tmp_path):
        note = create_note(str(tmp_path), "plan", "Plan X")
        assert ".claude/plans/" in str(note.path)

    def test_with_body(self, tmp_path):
        note = create_note(str(tmp_path), "note", "T", body="custom body")
        content = note.path.read_text()
        assert "custom body" in content

    def test_with_session_id(self, tmp_path):
        note = create_note(str(tmp_path), "note", "T", session_id="s123")
        content = note.path.read_text()
        assert "session: s123" in content

    def test_collision_avoidance(self, tmp_path):
        n1 = create_note(str(tmp_path), "note", "Same Title")
        n2 = create_note(str(tmp_path), "note", "Same Title")
        assert n1.path != n2.path
        assert n2.path.exists()


# ── delete_note ──────────────────────────────────────────────────────


class TestDeleteNote:
    def test_deletes_file(self, tmp_path):
        note = create_note(str(tmp_path), "note", "To Delete")
        assert note.path.exists()
        assert delete_note(note) is True
        assert not note.path.exists()

    def test_already_missing(self, tmp_path):
        note = NoteInfo(
            title="Ghost",
            created="",
            session_id="",
            path=tmp_path / "ghost.md",
            kind="note",
        )
        assert delete_note(note) is True


# ── read_note ────────────────────────────────────────────────────────


class TestReadNote:
    def test_reads_content(self, tmp_path):
        note = create_note(str(tmp_path), "note", "Readable")
        content = read_note(note)
        assert "title: Readable" in content

    def test_missing_file(self, tmp_path):
        note = NoteInfo(
            title="X",
            created="",
            session_id="",
            path=tmp_path / "nope.md",
            kind="note",
        )
        assert read_note(note) == "(failed to read)"


# ── rename_note ──────────────────────────────────────────────────────


class TestRenameNote:
    def test_updates_frontmatter(self, tmp_path):
        note = create_note(str(tmp_path), "note", "Old Name")
        rename_note(note, "New Name")
        content = note.path.read_text()
        assert "title: New Name" in content
        assert "title: Old Name" not in content
        assert note.title == "New Name"


# ── scan_notes ───────────────────────────────────────────────────────


class TestScanNotes:
    def test_scans_directory(self, tmp_path):
        create_note(str(tmp_path), "note", "Note A")
        create_note(str(tmp_path), "note", "Note B")
        results = scan_notes(str(tmp_path), "note")
        assert len(results) == 2
        titles = {n.title for n in results}
        assert "Note A" in titles
        assert "Note B" in titles

    def test_empty_dir(self, tmp_path):
        assert scan_notes(str(tmp_path), "plan") == []

    def test_kind_plan(self, tmp_path):
        create_note(str(tmp_path), "plan", "Plan X")
        results = scan_notes(str(tmp_path), "plan")
        assert len(results) == 1
        assert results[0].kind == "plan"


# ── NoteInfo.filename ────────────────────────────────────────────────


class TestNoteInfoFilename:
    def test_filename_property(self):
        note = NoteInfo(
            title="X",
            created="",
            session_id="",
            path=Path("/a/b/my-note.md"),
            kind="note",
        )
        assert note.filename == "my-note.md"
