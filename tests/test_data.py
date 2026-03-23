"""Tests for ccui.data — session parsing, timestamps, path helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ccui.data import (
    SessionInfo,
    _load_sessions_from_index,
    _parse_iso_datetime,
    _parse_session_from_jsonl,
    _parse_timestamp,
    _project_name_from_path,
    _read_original_path,
    _read_slug_and_title,
    delete_session,
    get_project_names,
    load_session_messages,
    resolve_cwd,
)

# ── _project_name_from_path ──────────────────────────────────────────


class TestProjectNameFromPath:
    def test_normal_path(self):
        assert _project_name_from_path("/Users/x/projects/sglang") == "sglang"

    def test_trailing_slash(self):
        assert _project_name_from_path("/Users/x/projects/sglang/") == "sglang"

    def test_empty(self):
        assert _project_name_from_path("") == "~"

    def test_root(self):
        assert _project_name_from_path("/") == "~"

    def test_home(self):
        assert _project_name_from_path("/Users/x") == "x"


# ── _parse_iso_datetime ──────────────────────────────────────────────


class TestParseIsoDatetime:
    def test_iso_with_z(self):
        dt = _parse_iso_datetime("2025-01-15T10:30:00Z")
        assert dt is not None
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.hour == 10

    def test_iso_with_offset(self):
        dt = _parse_iso_datetime("2025-01-15T10:30:00+08:00")
        assert dt is not None
        assert dt.hour == 10

    def test_none(self):
        assert _parse_iso_datetime(None) is None

    def test_empty(self):
        assert _parse_iso_datetime("") is None

    def test_invalid(self):
        assert _parse_iso_datetime("not-a-date") is None


# ── _parse_timestamp ─────────────────────────────────────────────────


class TestParseTimestamp:
    def test_ms_epoch(self):
        # 1705312200000 ms = 2024-01-15 some time
        dt = _parse_timestamp(1705312200000)
        assert dt is not None
        assert dt.year == 2024

    def test_float_epoch(self):
        dt = _parse_timestamp(1705312200000.0)
        assert dt is not None
        assert dt.year == 2024

    def test_iso_string(self):
        dt = _parse_timestamp("2025-01-15T10:30:00Z")
        assert dt is not None
        assert dt.year == 2025

    def test_none(self):
        assert _parse_timestamp(None) is None


# ── _read_slug_and_title ─────────────────────────────────────────────


class TestReadSlugAndTitle:
    def test_reads_last_values(self, write_jsonl):
        path = write_jsonl(
            "s1.jsonl",
            [
                {"slug": "first-slug"},
                {"slug": "second-slug", "customTitle": "My Title"},
                {"customTitle": "Final Title"},
            ],
        )
        slug, title = _read_slug_and_title(path)
        assert slug == "second-slug"
        assert title == "Final Title"

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        slug, title = _read_slug_and_title(p)
        assert slug == ""
        assert title == ""

    def test_missing_file(self, tmp_path):
        slug, title = _read_slug_and_title(tmp_path / "missing.jsonl")
        assert slug == ""
        assert title == ""

    def test_malformed_json_lines(self, tmp_path):
        p = tmp_path / "bad.jsonl"
        p.write_text('{"slug":"ok"}\nnot-json\n{"customTitle":"t"}\n')
        slug, title = _read_slug_and_title(p)
        assert slug == "ok"
        assert title == "t"


# ── _parse_session_from_jsonl ────────────────────────────────────────


class TestParseSessionFromJsonl:
    def test_basic_session(self, write_jsonl):
        path = write_jsonl(
            "sess1.jsonl",
            [
                {
                    "type": "user",
                    "timestamp": 1705312200000,
                    "message": {"content": "hello world"},
                },
                {
                    "type": "assistant",
                    "timestamp": 1705312260000,
                    "message": {"content": "hi there"},
                },
            ],
        )
        s = _parse_session_from_jsonl(path, "/Users/x/proj")
        assert s is not None
        assert s.session_id == "sess1"
        assert s.project_name == "proj"
        assert s.message_count == 2
        assert s.first_prompt == "hello world"

    def test_empty_file_returns_none(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        assert _parse_session_from_jsonl(p, "/x") is None

    def test_no_messages_returns_none(self, write_jsonl):
        path = write_jsonl("no_msg.jsonl", [{"type": "system", "data": "init"}])
        assert _parse_session_from_jsonl(path, "/x") is None

    def test_skips_tool_use_results(self, write_jsonl):
        path = write_jsonl(
            "tool.jsonl",
            [
                {
                    "type": "user",
                    "toolUseResult": True,
                    "message": {"content": "tool output"},
                },
                {
                    "type": "user",
                    "timestamp": 1705312200000,
                    "message": {"content": "real prompt"},
                },
                {
                    "type": "assistant",
                    "timestamp": 1705312260000,
                    "message": {"content": "response"},
                },
            ],
        )
        s = _parse_session_from_jsonl(path, "/x")
        assert s is not None
        assert s.first_prompt == "real prompt"

    def test_content_as_list(self, write_jsonl):
        path = write_jsonl(
            "list.jsonl",
            [
                {
                    "type": "user",
                    "timestamp": 1705312200000,
                    "message": {
                        "content": [
                            {"type": "text", "text": "list prompt"},
                            {"type": "image", "url": "..."},
                        ]
                    },
                },
                {
                    "type": "assistant",
                    "timestamp": 1705312260000,
                    "message": {"content": "ok"},
                },
            ],
        )
        s = _parse_session_from_jsonl(path, "/x")
        assert s is not None
        assert s.first_prompt == "list prompt"

    def test_extracts_slug_and_title(self, write_jsonl):
        path = write_jsonl(
            "meta.jsonl",
            [
                {"slug": "my-slug", "customTitle": "My Title"},
                {
                    "type": "user",
                    "timestamp": 1705312200000,
                    "message": {"content": "hi"},
                },
                {
                    "type": "assistant",
                    "timestamp": 1705312260000,
                    "message": {"content": "hey"},
                },
            ],
        )
        s = _parse_session_from_jsonl(path, "/x")
        assert s is not None
        assert s.slug == "my-slug"
        assert s.custom_title == "My Title"


# ── load_session_messages ────────────────────────────────────────────


class TestLoadSessionMessages:
    def test_basic_load(self, write_jsonl):
        path = write_jsonl(
            "chat.jsonl",
            [
                {"type": "user", "message": {"content": "question"}},
                {"type": "assistant", "message": {"content": "answer"}},
            ],
        )
        msgs = load_session_messages(path)
        assert len(msgs) == 2
        assert msgs[0] == {"role": "user", "text": "question"}
        assert msgs[1] == {"role": "assistant", "text": "answer"}

    def test_max_messages(self, write_jsonl):
        path = write_jsonl(
            "long.jsonl",
            [{"type": "user", "message": {"content": f"msg{i}"}} for i in range(10)],
        )
        msgs = load_session_messages(path, max_messages=3)
        assert len(msgs) == 3

    def test_skips_tool_use(self, write_jsonl):
        path = write_jsonl(
            "tool.jsonl",
            [
                {"type": "user", "toolUseResult": True, "message": {"content": "tool"}},
                {"type": "user", "message": {"content": "real"}},
            ],
        )
        msgs = load_session_messages(path)
        assert len(msgs) == 1
        assert msgs[0]["text"] == "real"

    def test_content_list(self, write_jsonl):
        path = write_jsonl(
            "list.jsonl",
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "part1"},
                            {"type": "text", "text": "part2"},
                        ]
                    },
                },
            ],
        )
        msgs = load_session_messages(path)
        assert len(msgs) == 1
        assert "part1" in msgs[0]["text"]
        assert "part2" in msgs[0]["text"]

    def test_missing_file(self, tmp_path):
        assert load_session_messages(tmp_path / "nope.jsonl") == []

    def test_skips_empty_content(self, write_jsonl):
        path = write_jsonl(
            "empty_content.jsonl",
            [
                {"type": "user", "message": {"content": ""}},
                {"type": "assistant", "message": {"content": "  "}},
                {"type": "user", "message": {"content": "real"}},
            ],
        )
        msgs = load_session_messages(path)
        assert len(msgs) == 1
        assert msgs[0]["text"] == "real"


# ── SessionInfo properties ───────────────────────────────────────────


class TestSessionInfoProperties:
    def test_date_str_uses_modified(self, tmp_session):
        assert tmp_session.date_str == "Jan 15"

    def test_date_str_falls_back_to_created(self, tmp_path):
        s = SessionInfo(
            session_id="x",
            project_path="",
            project_name="",
            first_prompt="",
            slug="",
            custom_title="",
            message_count=0,
            created=datetime(2025, 3, 1),
            modified=None,
            git_branch="",
            jsonl_path=tmp_path / "x.jsonl",
        )
        assert s.date_str == "Mar 01"

    def test_date_str_none(self, tmp_path):
        s = SessionInfo(
            session_id="x",
            project_path="",
            project_name="",
            first_prompt="",
            slug="",
            custom_title="",
            message_count=0,
            created=None,
            modified=None,
            git_branch="",
            jsonl_path=tmp_path / "x.jsonl",
        )
        assert s.date_str == "?"

    def test_created_str(self, tmp_session):
        assert tmp_session.created_str == "2025-01-15 10:00"

    def test_modified_str(self, tmp_session):
        assert tmp_session.modified_str == "2025-01-15 12:00"


# ── get_project_names ────────────────────────────────────────────────


class TestGetProjectNames:
    def test_unique_sorted(self, tmp_path):
        sessions = []
        for name in ["beta", "alpha", "beta", "gamma"]:
            sessions.append(
                SessionInfo(
                    session_id="x",
                    project_path="",
                    project_name=name,
                    first_prompt="",
                    slug="",
                    custom_title="",
                    message_count=0,
                    created=None,
                    modified=None,
                    git_branch="",
                    jsonl_path=tmp_path / "x.jsonl",
                )
            )
        assert get_project_names(sessions) == ["alpha", "beta", "gamma"]

    def test_empty(self):
        assert get_project_names([]) == []


# ── resolve_cwd ──────────────────────────────────────────────────────


class TestResolveCwd:
    def test_existing_dir(self, tmp_path):
        assert resolve_cwd(str(tmp_path)) == str(tmp_path)

    def test_missing_dir_walks_up(self, tmp_path):
        missing = tmp_path / "a" / "b" / "c"
        # tmp_path exists but a/b/c doesn't — should walk up to tmp_path
        result = resolve_cwd(str(missing))
        assert result is not None
        assert Path(result).is_dir()

    def test_empty_string(self):
        assert resolve_cwd("") is None

    def test_subdir_exists(self, tmp_path):
        sub = tmp_path / "real"
        sub.mkdir()
        assert resolve_cwd(str(sub)) == str(sub)


# ── _read_original_path ─────────────────────────────────────────────


class TestReadOriginalPath:
    def test_reads_path(self, tmp_path):
        index = tmp_path / "sessions-index.json"
        index.write_text('{"originalPath": "/Users/x/proj"}')
        assert _read_original_path(tmp_path) == "/Users/x/proj"

    def test_missing_index(self, tmp_path):
        assert _read_original_path(tmp_path) == ""

    def test_corrupt_json(self, tmp_path):
        (tmp_path / "sessions-index.json").write_text("not json")
        assert _read_original_path(tmp_path) == ""

    def test_no_original_path_key(self, tmp_path):
        (tmp_path / "sessions-index.json").write_text('{"entries": []}')
        assert _read_original_path(tmp_path) == ""


# ── _load_sessions_from_index ────────────────────────────────────────


class TestLoadSessionsFromIndex:
    def test_loads_entries(self, tmp_path):
        # Create a JSONL file for the session
        jsonl = tmp_path / "sess-abc.jsonl"
        jsonl.write_text('{"slug": "my-slug"}\n')

        index = tmp_path / "sessions-index.json"
        index.write_text(
            '{"originalPath": "/x/proj", "entries": ['
            '{"sessionId": "sess-abc", "firstPrompt": "hello", '
            '"messageCount": 3, "created": "2025-01-15T10:00:00Z", '
            '"modified": "2025-01-15T12:00:00Z", "gitBranch": "main"}'
            "]}"
        )
        sessions = _load_sessions_from_index(tmp_path)
        assert len(sessions) == 1
        s = sessions[0]
        assert s.session_id == "sess-abc"
        assert s.project_path == "/x/proj"
        assert s.first_prompt == "hello"
        assert s.message_count == 3
        assert s.slug == "my-slug"

    def test_missing_index(self, tmp_path):
        assert _load_sessions_from_index(tmp_path) == []

    def test_corrupt_index(self, tmp_path):
        (tmp_path / "sessions-index.json").write_text("bad json")
        assert _load_sessions_from_index(tmp_path) == []

    def test_empty_entries(self, tmp_path):
        (tmp_path / "sessions-index.json").write_text(
            '{"originalPath": "/x", "entries": []}'
        )
        assert _load_sessions_from_index(tmp_path) == []


# ── delete_session ───────────────────────────────────────────────────


class TestDeleteSession:
    def test_deletes_jsonl(self, tmp_path):
        jsonl = tmp_path / "s1.jsonl"
        jsonl.write_text("data")
        s = SessionInfo(
            session_id="s1",
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
        assert delete_session(s) is True
        assert not jsonl.exists()

    def test_deletes_companion_dir(self, tmp_path):
        jsonl = tmp_path / "s1.jsonl"
        jsonl.write_text("data")
        companion = tmp_path / "s1"
        companion.mkdir()
        (companion / "file.txt").write_text("snapshot")
        s = SessionInfo(
            session_id="s1",
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
        assert delete_session(s) is True
        assert not companion.exists()

    def test_removes_from_index(self, tmp_path):
        jsonl = tmp_path / "s1.jsonl"
        jsonl.write_text("data")
        index = tmp_path / "sessions-index.json"
        index.write_text('{"entries": [{"sessionId": "s1"}, {"sessionId": "s2"}]}')
        s = SessionInfo(
            session_id="s1",
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
        delete_session(s)
        import json

        data = json.loads(index.read_text())
        assert len(data["entries"]) == 1
        assert data["entries"][0]["sessionId"] == "s2"

    def test_missing_jsonl_ok(self, tmp_path):
        s = SessionInfo(
            session_id="ghost",
            project_path="/x",
            project_name="x",
            first_prompt="",
            slug="",
            custom_title="",
            message_count=0,
            created=None,
            modified=None,
            git_branch="",
            jsonl_path=tmp_path / "ghost.jsonl",
        )
        assert delete_session(s) is True
