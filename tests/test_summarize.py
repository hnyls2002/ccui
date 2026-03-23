"""Tests for ccui.summarize — context extraction, filtering, note content reading."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ccui.data import SessionInfo
from ccui.notes import NoteInfo
from ccui.store import AppStore
from ccui.summarize import (
    SAMPLE_SIZE,
    _extract_context,
    _needs_summary,
    _read_note_content,
    notes_needing_summary,
    sessions_needing_summary,
)


def _make_session(
    tmp_path: Path,
    sid: str = "s1",
    custom_title: str = "",
    messages: list[dict] | None = None,
) -> SessionInfo:
    jsonl = tmp_path / f"{sid}.jsonl"
    if messages is None:
        messages = [
            {"type": "user", "message": {"content": f"user msg {i}"}} for i in range(3)
        ] + [
            {"type": "assistant", "message": {"content": f"assistant msg {i}"}}
            for i in range(3)
        ]
    lines = [json.dumps(m) for m in messages]
    jsonl.write_text("\n".join(lines) + "\n")
    return SessionInfo(
        session_id=sid,
        project_path="/x/proj",
        project_name="proj",
        first_prompt="hi",
        slug="",
        custom_title=custom_title,
        message_count=len(messages),
        created=datetime(2025, 1, 1),
        modified=datetime(2025, 1, 1),
        git_branch="main",
        jsonl_path=jsonl,
    )


# ── _extract_context ─────────────────────────────────────────────────


class TestExtractContext:
    def test_short_session(self, tmp_path):
        session = _make_session(
            tmp_path,
            messages=[
                {"type": "user", "message": {"content": "hello"}},
                {"type": "assistant", "message": {"content": "hi"}},
            ],
        )
        ctx = _extract_context(session)
        assert "hello" in ctx
        assert "hi" in ctx
        assert "omitted" not in ctx

    def test_long_session_shows_omitted(self, tmp_path):
        msgs = []
        for i in range(SAMPLE_SIZE * 3):
            msgs.append({"type": "user", "message": {"content": f"msg-{i}"}})
        session = _make_session(tmp_path, messages=msgs)
        ctx = _extract_context(session)
        assert "omitted" in ctx
        assert "msg-0" in ctx  # head
        assert f"msg-{SAMPLE_SIZE * 3 - 1}" in ctx  # tail

    def test_empty_session(self, tmp_path):
        session = _make_session(tmp_path, messages=[])
        assert _extract_context(session) == ""

    def test_truncates_long_messages(self, tmp_path):
        long_text = "x" * 1000
        session = _make_session(
            tmp_path,
            messages=[
                {"type": "user", "message": {"content": long_text}},
                {"type": "assistant", "message": {"content": "ok"}},
            ],
        )
        ctx = _extract_context(session)
        # Each message truncated to 500 chars
        assert len(ctx) < len(long_text)


# ── _needs_summary ───────────────────────────────────────────────────


class TestNeedsSummary:
    def test_needs_both(self, tmp_path):
        store = AppStore()
        s = _make_session(tmp_path)
        assert _needs_summary(s, store) is True

    def test_has_title_only(self, tmp_path):
        store = AppStore()
        s = _make_session(tmp_path, custom_title="My Title")
        assert _needs_summary(s, store) is True

    def test_has_summary_only(self, tmp_path):
        store = AppStore()
        store.summaries = {"s1": "a summary"}
        s = _make_session(tmp_path)
        assert _needs_summary(s, store) is True

    def test_has_both(self, tmp_path):
        store = AppStore()
        store.summaries = {"s1": "a summary"}
        s = _make_session(tmp_path, custom_title="My Title")
        assert _needs_summary(s, store) is False


# ── sessions_needing_summary ─────────────────────────────────────────


class TestSessionsNeedingSummary:
    def test_filters(self, tmp_path):
        store = AppStore()
        s1 = _make_session(tmp_path, sid="s1", custom_title="")
        s2 = _make_session(tmp_path, sid="s2", custom_title="Done")
        store.sessions = [s1, s2]
        store.summaries = {"s2": "summarized"}
        result = sessions_needing_summary(store)
        assert len(result) == 1
        assert result[0].session_id == "s1"


# ── _read_note_content ──────────────────────────────────────────────


class TestReadNoteContent:
    def test_strips_frontmatter(self, tmp_path):
        p = tmp_path / "note.md"
        p.write_text("---\ntitle: Test\n---\n\nActual content here\n")
        note = NoteInfo(title="Test", created="", session_id="", path=p, kind="note")
        content = _read_note_content(note)
        assert "title:" not in content
        assert "Actual content here" in content

    def test_no_frontmatter(self, tmp_path):
        p = tmp_path / "plain.md"
        p.write_text("# Just content\n\nBody\n")
        note = NoteInfo(title="X", created="", session_id="", path=p, kind="note")
        content = _read_note_content(note)
        assert "Just content" in content

    def test_missing_file(self, tmp_path):
        note = NoteInfo(
            title="X",
            created="",
            session_id="",
            path=tmp_path / "nope.md",
            kind="note",
        )
        assert _read_note_content(note) == ""

    def test_truncates(self, tmp_path):
        p = tmp_path / "long.md"
        p.write_text("x" * 5000)
        note = NoteInfo(title="X", created="", session_id="", path=p, kind="note")
        content = _read_note_content(note)
        assert len(content) <= 2000


# ── notes_needing_summary ────────────────────────────────────────────


class TestNotesNeedingSummary:
    def test_filters(self, tmp_path):
        n1 = NoteInfo(
            title="A", created="", session_id="", path=tmp_path / "a.md", kind="note"
        )
        n2 = NoteInfo(
            title="B", created="", session_id="", path=tmp_path / "b.md", kind="note"
        )
        store = AppStore()
        store.note_summaries = {str(tmp_path / "b.md"): "has summary"}
        result = notes_needing_summary([n1, n2], store)
        assert len(result) == 1
        assert result[0].title == "A"
