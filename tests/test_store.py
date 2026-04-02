"""Tests for ccui.store — AppStore filtering, display, state management."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from ccui.data import SessionInfo
from ccui.store import AppStore, _load_note_summaries, _load_summaries


def _make_session(
    sid: str = "s1",
    project_name: str = "proj",
    custom_title: str = "",
    **kwargs,
) -> SessionInfo:
    defaults = dict(
        session_id=sid,
        project_path=f"/x/{project_name}",
        project_name=project_name,
        first_prompt="hi",
        slug="",
        custom_title=custom_title,
        message_count=1,
        created=datetime(2025, 1, 1),
        modified=datetime(2025, 1, 1),
        git_branch="main",
        jsonl_path=Path("/tmp/fake.jsonl"),
    )
    defaults.update(kwargs)
    return SessionInfo(**defaults)


# ── display_title / display_summary ──────────────────────────────────


class TestDisplayTitle:
    def test_with_custom_title(self):
        store = AppStore()
        s = _make_session(custom_title="My Title")
        assert store.display_title(s) == "My Title"

    def test_without_custom_title(self):
        store = AppStore()
        s = _make_session(sid="abcdef12-3456", custom_title="")
        assert store.display_title(s) == "abcdef12"

    def test_display_summary_present(self):
        store = AppStore()
        store.summaries = {"s1": {"summary": "a summary", "message_count": 5}}
        s = _make_session(sid="s1")
        assert store.display_summary(s) == "a summary"

    def test_display_summary_legacy_string(self):
        store = AppStore()
        store.summaries = {"s1": "a summary"}
        s = _make_session(sid="s1")
        assert store.display_summary(s) == "a summary"

    def test_display_summary_missing(self):
        store = AppStore()
        s = _make_session(sid="s1")
        assert store.display_summary(s) == ""


# ── visible_sessions ─────────────────────────────────────────────────


class TestVisibleSessions:
    def _setup_store(self) -> AppStore:
        store = AppStore()
        store.sessions = [
            _make_session(sid="s1", project_name="alpha", custom_title="Fix bug"),
            _make_session(sid="s2", project_name="beta", custom_title="Add feature"),
            _make_session(sid="s3", project_name="alpha", custom_title="Refactor"),
        ]
        return store

    def test_all_visible(self):
        store = self._setup_store()
        assert len(store.visible_sessions()) == 3

    def test_filter_by_project(self):
        store = self._setup_store()
        result = store.visible_sessions("alpha")
        assert len(result) == 2
        assert all(s.project_name == "alpha" for s in result)

    def test_global_shows_all(self):
        store = self._setup_store()
        assert len(store.visible_sessions("GLOBAL")) == 3

    def test_archived_hidden_by_default(self):
        store = self._setup_store()
        store.archived_ids = {"s2"}
        result = store.visible_sessions()
        assert len(result) == 2
        assert all(s.session_id != "s2" for s in result)

    def test_show_archived(self):
        store = self._setup_store()
        store.archived_ids = {"s2"}
        store.show_archived = True
        assert len(store.visible_sessions()) == 3

    def test_search_by_title(self):
        store = self._setup_store()
        store.search_query = "fix"
        result = store.visible_sessions()
        assert len(result) == 1
        assert result[0].session_id == "s1"

    def test_search_by_project(self):
        store = self._setup_store()
        store.search_query = "beta"
        result = store.visible_sessions()
        assert len(result) == 1
        assert result[0].session_id == "s2"

    def test_search_by_summary(self):
        store = self._setup_store()
        store.summaries = {"s3": {"summary": "code cleanup", "message_count": 5}}
        store.search_query = "cleanup"
        result = store.visible_sessions()
        assert len(result) == 1
        assert result[0].session_id == "s3"

    def test_search_case_insensitive(self):
        store = self._setup_store()
        store.search_query = "FIX"
        assert len(store.visible_sessions()) == 1

    def test_combined_archive_and_search(self):
        store = self._setup_store()
        store.archived_ids = {"s1"}
        store.search_query = "fix"
        result = store.visible_sessions()
        assert len(result) == 0  # s1 matches search but is archived


# ── remove_session ───────────────────────────────────────────────────


class TestRemoveSession:
    def test_removes_by_id(self):
        store = AppStore()
        store.sessions = [_make_session(sid="s1"), _make_session(sid="s2")]
        store.remove_session("s1")
        assert len(store.sessions) == 1
        assert store.sessions[0].session_id == "s2"

    def test_remove_nonexistent_noop(self):
        store = AppStore()
        store.sessions = [_make_session(sid="s1")]
        store.remove_session("s999")
        assert len(store.sessions) == 1


# ── project_names ────────────────────────────────────────────────────


class TestProjectNames:
    def test_returns_sorted_unique(self):
        store = AppStore()
        store.sessions = [
            _make_session(sid="s1", project_name="beta"),
            _make_session(sid="s2", project_name="alpha"),
            _make_session(sid="s3", project_name="beta"),
        ]
        assert store.project_names == ["alpha", "beta"]


# ── _load_summaries / _load_note_summaries ───────────────────────────


class TestLoadSummaries:
    def test_loads_valid(self, tmp_path):
        f = tmp_path / "summaries.json"
        f.write_text(json.dumps({"s1": "summary one", "s2": "summary two"}))
        with patch("ccui.store.SUMMARIES_FILE", f):
            result = _load_summaries()
            assert result == {"s1": "summary one", "s2": "summary two"}

    def test_missing_file(self, tmp_path):
        with patch("ccui.store.SUMMARIES_FILE", tmp_path / "nope.json"):
            assert _load_summaries() == {}

    def test_corrupt_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json")
        with patch("ccui.store.SUMMARIES_FILE", f):
            assert _load_summaries() == {}

    def test_non_dict_json(self, tmp_path):
        f = tmp_path / "list.json"
        f.write_text(json.dumps(["a", "b"]))
        with patch("ccui.store.SUMMARIES_FILE", f):
            assert _load_summaries() == {}


class TestLoadNoteSummaries:
    def test_loads_valid(self, tmp_path):
        f = tmp_path / "note-summaries.json"
        f.write_text(json.dumps({"/a/b.md": "note summary"}))
        with patch("ccui.store.NOTE_SUMMARIES_FILE", f):
            result = _load_note_summaries()
            assert result == {"/a/b.md": "note summary"}

    def test_missing_file(self, tmp_path):
        with patch("ccui.store.NOTE_SUMMARIES_FILE", tmp_path / "nope.json"):
            assert _load_note_summaries() == {}

    def test_corrupt_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("bad")
        with patch("ccui.store.NOTE_SUMMARIES_FILE", f):
            assert _load_note_summaries() == {}
