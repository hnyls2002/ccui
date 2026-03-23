"""Aggressive edge-case tests — designed to find real bugs."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ccui.config import _parse_frontmatter as config_parse_frontmatter
from ccui.data import SessionInfo, _parse_session_from_jsonl, load_session_messages
from ccui.notes import NoteInfo
from ccui.notes import _parse_frontmatter as notes_parse_frontmatter
from ccui.notes import _slugify, create_note, rename_note, scan_notes
from ccui.store import AppStore
from ccui.summarize import SAMPLE_SIZE, _extract_context, _read_note_content

# ═══════════════════════════════════════════════════════════════════════
# notes._slugify — Unicode and degenerate inputs
# ═══════════════════════════════════════════════════════════════════════


class TestSlugifyEdgeCases:
    def test_chinese_title(self):
        """Chinese chars should produce something meaningful, not 'untitled'."""
        result = _slugify("修复认证问题")
        assert result != "untitled", f"Chinese title slugified to 'untitled': {result}"

    def test_mixed_chinese_english(self):
        result = _slugify("fix-认证-bug")
        assert "fix" in result
        assert result != "untitled"

    def test_japanese_title(self):
        result = _slugify("テスト計画")
        assert result != "untitled"

    def test_emoji_title(self):
        """Emoji-only title — may fall back to untitled but shouldn't crash."""
        result = _slugify("🎉🎊")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_all_spaces(self):
        result = _slugify("   ")
        assert result == "untitled"

    def test_newlines_in_title(self):
        result = _slugify("hello\nworld")
        assert "\n" not in result

    def test_tab_in_title(self):
        result = _slugify("hello\tworld")
        assert "\t" not in result


# ═══════════════════════════════════════════════════════════════════════
# notes._parse_frontmatter — tricky YAML-like edge cases
# ═══════════════════════════════════════════════════════════════════════


class TestNotesFrontmatterEdgeCases:
    def test_triple_dash_in_body_does_not_affect_frontmatter(self, tmp_path):
        """The parser should stop at the FIRST closing --- and not be confused by --- in body."""
        p = tmp_path / "note.md"
        p.write_text("---\ntitle: Real Title\n---\n\nBody\n---\nMore body\n")
        fm = notes_parse_frontmatter(p)
        assert fm["title"] == "Real Title"

    def test_value_with_colon(self, tmp_path):
        """Values containing colons (like URLs) should be captured fully."""
        p = tmp_path / "note.md"
        p.write_text("---\ntitle: Fix: auth bug\n---\n")
        fm = notes_parse_frontmatter(p)
        # The regex captures everything after first colon-space
        assert "Fix" in fm.get("title", "")

    def test_empty_value(self, tmp_path):
        p = tmp_path / "note.md"
        p.write_text("---\ntitle: \n---\n")
        fm = notes_parse_frontmatter(p)
        # Empty value after colon — regex requires (.+), won't match
        assert "title" not in fm or fm["title"] == ""

    def test_only_opening_delimiter(self, tmp_path):
        """Frontmatter with no closing --- — should return partial or empty."""
        p = tmp_path / "note.md"
        p.write_text("---\ntitle: Orphan\nno closing delimiter\n")
        fm = notes_parse_frontmatter(p)
        # Parser iterates until EOF without finding ---, captures everything
        assert fm.get("title") == "Orphan"


# ═══════════════════════════════════════════════════════════════════════
# config._parse_frontmatter — different regex, different edge cases
# ═══════════════════════════════════════════════════════════════════════


class TestConfigFrontmatterEdgeCases:
    def test_value_with_colon_url(self, tmp_path):
        p = tmp_path / "rule.md"
        p.write_text("---\nurl: https://example.com:8080/path\n---\n")
        fm = config_parse_frontmatter(p)
        assert "https" in fm.get("url", "")

    def test_value_with_equals(self, tmp_path):
        """Key: value where value has = sign."""
        p = tmp_path / "rule.md"
        p.write_text("---\ncommand: ENV=prod make build\n---\n")
        fm = config_parse_frontmatter(p)
        assert "ENV=prod" in fm.get("command", "")

    def test_numeric_key(self, tmp_path):
        p = tmp_path / "rule.md"
        p.write_text("---\n123key: val\n---\n")
        fm = config_parse_frontmatter(p)
        # regex starts with \w, which matches digits
        assert fm.get("123key") == "val"


# ═══════════════════════════════════════════════════════════════════════
# notes.rename_note — missing title line
# ═══════════════════════════════════════════════════════════════════════


class TestRenameNoteEdgeCases:
    def test_no_title_line(self, tmp_path):
        """If file has no 'title:' line, rename inserts it after opening ---."""
        p = tmp_path / "note.md"
        p.write_text("---\ncreated: 2025-01-01\n---\n\nBody\n")
        note = NoteInfo(
            title="Old", created="2025-01-01", session_id="", path=p, kind="note"
        )
        rename_note(note, "New Name")
        content = p.read_text()
        assert note.title == "New Name"
        assert "title: New Name" in content

    def test_rename_missing_file(self, tmp_path):
        """Rename on a deleted file should not crash."""
        note = NoteInfo(
            title="X",
            created="",
            session_id="",
            path=tmp_path / "gone.md",
            kind="note",
        )
        # Should not raise
        rename_note(note, "New")


# ═══════════════════════════════════════════════════════════════════════
# store.display_title — short session IDs
# ═══════════════════════════════════════════════════════════════════════


class TestDisplayTitleEdgeCases:
    def test_short_session_id(self):
        store = AppStore()
        s = SessionInfo(
            session_id="abc",
            project_path="",
            project_name="",
            first_prompt="",
            slug="",
            custom_title="",
            message_count=0,
            created=None,
            modified=None,
            git_branch="",
            jsonl_path=Path("/fake"),
        )
        result = store.display_title(s)
        assert result == "abc"  # Python slicing is safe

    def test_empty_session_id(self):
        store = AppStore()
        s = SessionInfo(
            session_id="",
            project_path="",
            project_name="",
            first_prompt="",
            slug="",
            custom_title="",
            message_count=0,
            created=None,
            modified=None,
            git_branch="",
            jsonl_path=Path("/fake"),
        )
        result = store.display_title(s)
        assert result == ""  # empty string sliced is empty


# ═══════════════════════════════════════════════════════════════════════
# summarize._extract_context — boundary at SAMPLE_SIZE * 2 + 1
# ═══════════════════════════════════════════════════════════════════════


def _make_session_with_msgs(
    tmp_path: Path, n_msgs: int, sid: str = "s1"
) -> SessionInfo:
    msgs = [{"type": "user", "message": {"content": f"msg-{i}"}} for i in range(n_msgs)]
    jsonl = tmp_path / f"{sid}.jsonl"
    jsonl.write_text("\n".join(json.dumps(m) for m in msgs) + "\n")
    return SessionInfo(
        session_id=sid,
        project_path="/x",
        project_name="x",
        first_prompt="",
        slug="",
        custom_title="",
        message_count=n_msgs,
        created=datetime(2025, 1, 1),
        modified=datetime(2025, 1, 1),
        git_branch="",
        jsonl_path=jsonl,
    )


class TestExtractContextBoundary:
    def test_exactly_double_sample_size(self, tmp_path):
        """At exactly 2*SAMPLE_SIZE, all messages should be included."""
        n = SAMPLE_SIZE * 2
        session = _make_session_with_msgs(tmp_path, n)
        ctx = _extract_context(session)
        assert "omitted" not in ctx
        # All messages should be present
        for i in range(n):
            assert f"msg-{i}" in ctx

    def test_double_sample_size_plus_one(self, tmp_path):
        """At 2*SAMPLE_SIZE + 1, one message in the middle gets dropped.

        head = [0..SAMPLE_SIZE-1], tail = [SAMPLE_SIZE+1..2*SAMPLE_SIZE]
        Message SAMPLE_SIZE is lost.
        """
        n = SAMPLE_SIZE * 2 + 1
        session = _make_session_with_msgs(tmp_path, n)
        ctx = _extract_context(session)
        assert "omitted" in ctx
        # The first and last SAMPLE_SIZE messages should be present
        for i in range(SAMPLE_SIZE):
            assert f"msg-{i}" in ctx, f"msg-{i} missing from head"
        for i in range(n - SAMPLE_SIZE, n):
            assert f"msg-{i}" in ctx, f"msg-{i} missing from tail"
        # Message at index SAMPLE_SIZE is the one that's dropped
        dropped = f"msg-{SAMPLE_SIZE}"
        assert dropped not in ctx, f"{dropped} should be omitted but was found"

    def test_double_sample_size_plus_two(self, tmp_path):
        """At 2*SAMPLE_SIZE + 2, two messages are dropped."""
        n = SAMPLE_SIZE * 2 + 2
        session = _make_session_with_msgs(tmp_path, n)
        ctx = _extract_context(session)
        assert "omitted" in ctx
        # Verify omitted count is correct
        expected_omitted = n - SAMPLE_SIZE * 2
        assert f"{expected_omitted} messages omitted" in ctx


# ═══════════════════════════════════════════════════════════════════════
# summarize._read_note_content — unclosed frontmatter
# ═══════════════════════════════════════════════════════════════════════


class TestReadNoteContentEdgeCases:
    def test_unclosed_frontmatter(self, tmp_path):
        """Unclosed frontmatter: opening --- is stripped, rest treated as body."""
        p = tmp_path / "bad.md"
        p.write_text("---\ntitle: Leaked\nThis is not frontmatter\n\n# Real content\n")
        note = NoteInfo(title="X", created="", session_id="", path=p, kind="note")
        content = _read_note_content(note)
        # Opening --- is stripped; remaining lines (including "title: Leaked") remain
        # since we can't distinguish frontmatter from body without closing ---
        assert "---" not in content.split("\n")[0] if content else True
        assert "Real content" in content

    def test_empty_frontmatter(self, tmp_path):
        p = tmp_path / "empty_fm.md"
        p.write_text("---\n---\n\nJust body\n")
        note = NoteInfo(title="X", created="", session_id="", path=p, kind="note")
        content = _read_note_content(note)
        assert "Just body" in content
        assert "---" not in content

    def test_only_frontmatter_no_body(self, tmp_path):
        p = tmp_path / "no_body.md"
        p.write_text("---\ntitle: Only FM\n---\n")
        note = NoteInfo(title="X", created="", session_id="", path=p, kind="note")
        content = _read_note_content(note)
        assert content == ""


# ═══════════════════════════════════════════════════════════════════════
# data._parse_session_from_jsonl — weird content types
# ═══════════════════════════════════════════════════════════════════════


class TestParseSessionWeirdContent:
    def test_message_is_none(self, tmp_path):
        """Message key exists but is None — should not crash.

        message_count is still incremented (type=user), but content
        extraction gracefully handles None via isinstance check.
        """
        p = tmp_path / "null_msg.jsonl"
        p.write_text(
            json.dumps(
                {
                    "type": "user",
                    "timestamp": 1705312200000,
                    "message": None,
                }
            )
            + "\n"
        )
        result = _parse_session_from_jsonl(p, "/x")
        # message_count=1 because type is "user", but no readable content
        assert result is not None
        assert result.message_count == 1
        assert result.first_prompt == "No prompt"

    def test_message_is_string(self, tmp_path):
        """Message is a string instead of a dict."""
        p = tmp_path / "str_msg.jsonl"
        p.write_text(
            json.dumps(
                {
                    "type": "user",
                    "timestamp": 1705312200000,
                    "message": "just a string",
                }
            )
            + "\n"
        )
        result = _parse_session_from_jsonl(p, "/x")
        # message_count incremented but content extraction fails silently
        # Result depends on whether message_count > 0
        if result is not None:
            assert result.first_prompt == "No prompt"

    def test_content_is_integer(self, tmp_path):
        """Content field is an integer instead of str/list."""
        p = tmp_path / "int_content.jsonl"
        p.write_text(
            json.dumps(
                {
                    "type": "user",
                    "timestamp": 1705312200000,
                    "message": {"content": 42},
                }
            )
            + "\n"
        )
        result = _parse_session_from_jsonl(p, "/x")
        if result is not None:
            assert result.first_prompt == "No prompt"

    def test_content_is_none(self, tmp_path):
        """Content field is None."""
        p = tmp_path / "none_content.jsonl"
        p.write_text(
            json.dumps(
                {
                    "type": "user",
                    "timestamp": 1705312200000,
                    "message": {"content": None},
                }
            )
            + "\n"
        )
        result = _parse_session_from_jsonl(p, "/x")
        # Should not crash
        assert result is None or result.first_prompt == "No prompt"


# ═══════════════════════════════════════════════════════════════════════
# data.load_session_messages — weird content types
# ═══════════════════════════════════════════════════════════════════════


class TestLoadMessagesWeirdContent:
    def test_message_is_none(self, tmp_path):
        p = tmp_path / "chat.jsonl"
        p.write_text(
            json.dumps(
                {
                    "type": "user",
                    "message": None,
                }
            )
            + "\n"
        )
        msgs = load_session_messages(p)
        assert msgs == []  # skipped

    def test_message_is_string(self, tmp_path):
        p = tmp_path / "chat.jsonl"
        p.write_text(
            json.dumps(
                {
                    "type": "user",
                    "message": "raw string",
                }
            )
            + "\n"
        )
        msgs = load_session_messages(p)
        assert msgs == []  # not a dict, skipped

    def test_content_is_dict(self, tmp_path):
        """Content is a dict (not str or list) — unusual but possible."""
        p = tmp_path / "chat.jsonl"
        p.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": {"key": "val"}},
                }
            )
            + "\n"
        )
        msgs = load_session_messages(p)
        assert msgs == []  # neither str nor list


# ═══════════════════════════════════════════════════════════════════════
# notes.create_note + scan_notes round-trip with edge-case titles
# ═══════════════════════════════════════════════════════════════════════


class TestCreateNoteRoundTrip:
    def test_title_with_slashes(self, tmp_path):
        """Title with path separators shouldn't create subdirectories."""
        note = create_note(str(tmp_path), "note", "path/to/fix")
        assert note.path.parent.name == "notes"
        assert note.path.exists()

    def test_very_long_title(self, tmp_path):
        title = "a" * 200
        note = create_note(str(tmp_path), "note", title)
        assert note.path.exists()
        assert len(note.path.name) < 100  # slug truncated

    def test_scan_after_create(self, tmp_path):
        """Create several notes and verify scan finds them all with correct metadata."""
        create_note(str(tmp_path), "note", "Alpha", session_id="s1")
        create_note(str(tmp_path), "note", "Beta")
        notes = scan_notes(str(tmp_path), "note")
        assert len(notes) == 2
        titles = {n.title for n in notes}
        assert titles == {"Alpha", "Beta"}
        # Verify session_id is preserved through round-trip
        alpha = next(n for n in notes if n.title == "Alpha")
        assert alpha.session_id == "s1"
