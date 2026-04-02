"""Tests for ccui.summarize — context extraction, filtering, note content reading."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from ccui.data import SessionInfo
from ccui.notes import NoteInfo
from ccui.store import AppStore
from ccui.summarize import (
    SAMPLE_SIZE,
    _append_custom_title,
    _extract_context,
    _needs_summary,
    _read_note_content,
    _save_note_summaries,
    _save_summaries,
    count_new_and_update,
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
        store.summaries = {"s1": {"summary": "a summary", "message_count": 6}}
        s = _make_session(tmp_path)
        assert _needs_summary(s, store) is True

    def test_has_both(self, tmp_path):
        store = AppStore()
        store.summaries = {"s1": {"summary": "a summary", "message_count": 6}}
        s = _make_session(tmp_path, custom_title="My Title")
        assert _needs_summary(s, store) is False

    def test_has_both_legacy_string(self, tmp_path):
        """Backward compat: old string format still counts as having summary."""
        store = AppStore()
        store.summaries = {"s1": "a summary"}
        s = _make_session(tmp_path, custom_title="My Title")
        assert _needs_summary(s, store) is False

    def test_resummary_on_message_drift(self, tmp_path):
        """Re-summarize when message count drifts beyond threshold."""
        store = AppStore()
        store.summaries = {"s1": {"summary": "old summary", "message_count": 6}}
        s = _make_session(tmp_path, custom_title="My Title")
        # Default _make_session creates 6 messages, matching stored count
        assert _needs_summary(s, store) is False
        # Now simulate session growing significantly (6 -> 20 messages)
        s.message_count = 20
        assert _needs_summary(s, store) is True

    def test_no_resummary_on_small_drift(self, tmp_path):
        """Don't re-summarize for minor message count changes."""
        store = AppStore()
        store.summaries = {"s1": {"summary": "summary", "message_count": 10}}
        s = _make_session(tmp_path, custom_title="My Title")
        s.message_count = 11  # only 10% drift, below 30% threshold
        assert _needs_summary(s, store) is False


# ── sessions_needing_summary ─────────────────────────────────────────


class TestSessionsNeedingSummary:
    def test_filters(self, tmp_path):
        store = AppStore()
        s1 = _make_session(tmp_path, sid="s1", custom_title="")
        s2 = _make_session(tmp_path, sid="s2", custom_title="Done")
        store.sessions = [s1, s2]
        store.summaries = {"s2": {"summary": "summarized", "message_count": 6}}
        result = sessions_needing_summary(store)
        assert len(result) == 1
        assert result[0].session_id == "s1"


# ── count_new_and_update ────────────────────────────────────────────


class TestCountNewAndUpdate:
    def test_all_new(self, tmp_path):
        store = AppStore()
        s1 = _make_session(tmp_path, sid="s1", custom_title="")
        s2 = _make_session(tmp_path, sid="s2", custom_title="")
        store.sessions = [s1, s2]
        new, update = count_new_and_update(store)
        assert new == 2
        assert update == 0

    def test_all_update(self, tmp_path):
        store = AppStore()
        s1 = _make_session(tmp_path, sid="s1", custom_title="Title1")
        s1.message_count = 20  # drift from stored 6
        s2 = _make_session(tmp_path, sid="s2", custom_title="Title2")
        s2.message_count = 20
        store.sessions = [s1, s2]
        store.summaries = {
            "s1": {"summary": "old", "message_count": 6},
            "s2": {"summary": "old", "message_count": 6},
        }
        new, update = count_new_and_update(store)
        assert new == 0
        assert update == 2

    def test_mixed(self, tmp_path):
        store = AppStore()
        s1 = _make_session(tmp_path, sid="s1", custom_title="")  # new
        s2 = _make_session(tmp_path, sid="s2", custom_title="Title2")
        s2.message_count = 20  # update (drift)
        store.sessions = [s1, s2]
        store.summaries = {"s2": {"summary": "old", "message_count": 6}}
        new, update = count_new_and_update(store)
        assert new == 1
        assert update == 1

    def test_none_pending(self, tmp_path):
        store = AppStore()
        s1 = _make_session(tmp_path, sid="s1", custom_title="Title")
        store.sessions = [s1]
        store.summaries = {"s1": {"summary": "done", "message_count": 6}}
        new, update = count_new_and_update(store)
        assert new == 0
        assert update == 0


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


# ── _save_summaries ──────────────────────────────────────────────────


class TestSaveSummaries:
    def test_writes_json(self, tmp_path):
        f = tmp_path / "summaries.json"
        with patch("ccui.summarize.SUMMARIES_FILE", f):
            _save_summaries({"s1": "sum1", "s2": "sum2"})
        data = json.loads(f.read_text())
        assert data == {"s1": "sum1", "s2": "sum2"}

    def test_unicode(self, tmp_path):
        f = tmp_path / "summaries.json"
        with patch("ccui.summarize.SUMMARIES_FILE", f):
            _save_summaries({"s1": "修复 auth 问题"})
        content = f.read_text()
        assert "修复" in content  # ensure_ascii=False


class TestSaveNoteSummaries:
    def test_writes_json(self, tmp_path):
        f = tmp_path / "note-summaries.json"
        with patch("ccui.summarize.NOTE_SUMMARIES_FILE", f):
            _save_note_summaries({"/a/b.md": "note sum"})
        data = json.loads(f.read_text())
        assert data == {"/a/b.md": "note sum"}


# ── _append_custom_title ─────────────────────────────────────────────


class TestAppendCustomTitle:
    def test_appends_to_jsonl(self, tmp_path):
        jsonl = tmp_path / "s1.jsonl"
        jsonl.write_text('{"type":"user","message":{"content":"hi"}}\n')
        s = SessionInfo(
            session_id="s1",
            project_path="/x",
            project_name="x",
            first_prompt="hi",
            slug="",
            custom_title="",
            message_count=1,
            created=datetime(2025, 1, 1),
            modified=datetime(2025, 1, 1),
            git_branch="",
            jsonl_path=jsonl,
        )
        _append_custom_title(s, "new-title")
        lines = jsonl.read_text().strip().split("\n")
        assert len(lines) == 2
        last = json.loads(lines[-1])
        assert last["customTitle"] == "new-title"

    def test_unicode_title(self, tmp_path):
        jsonl = tmp_path / "s2.jsonl"
        jsonl.write_text("")
        s = SessionInfo(
            session_id="s2",
            project_path="/x",
            project_name="x",
            first_prompt="",
            slug="",
            custom_title="",
            message_count=0,
            created=None,
            modified=None,
            git_branch="",
            jsonl_path=jsonl,
        )
        _append_custom_title(s, "修复-bug")
        content = jsonl.read_text()
        assert "修复-bug" in content
