"""Tests for load_all_sessions — full pipeline with simulated project dirs."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from ccui.data import load_all_sessions


def _make_project(
    projects_dir: Path,
    dir_name: str,
    original_path: str,
    sessions: list[dict],
) -> Path:
    """Create a simulated project directory with sessions-index.json and JSONL files."""
    proj_dir = projects_dir / dir_name
    proj_dir.mkdir(parents=True)

    entries = []
    for s in sessions:
        sid = s["sessionId"]
        jsonl = proj_dir / f"{sid}.jsonl"
        msgs = s.get("messages", [])
        lines = [json.dumps(m) for m in msgs]
        jsonl.write_text("\n".join(lines) + "\n" if lines else "")
        entries.append(
            {
                "sessionId": sid,
                "firstPrompt": s.get("firstPrompt", "hi"),
                "messageCount": s.get("messageCount", len(msgs)),
                "created": s.get("created", "2025-01-10T10:00:00Z"),
                "modified": s.get("modified", "2025-01-10T12:00:00Z"),
                "gitBranch": s.get("gitBranch", ""),
            }
        )

    index = {
        "originalPath": original_path,
        "entries": entries,
    }
    (proj_dir / "sessions-index.json").write_text(json.dumps(index))
    return proj_dir


class TestLoadAllSessions:
    def test_loads_from_index(self, tmp_path):
        projects_dir = tmp_path / "projects"
        _make_project(
            projects_dir,
            "-Users-x-myproject",
            "/Users/x/myproject",
            [
                {
                    "sessionId": "sess-aaa",
                    "messages": [
                        {"type": "user", "message": {"content": "hello"}},
                        {"type": "assistant", "message": {"content": "hi"}},
                    ],
                    "messageCount": 2,
                },
            ],
        )
        with patch("ccui.data.PROJECTS_DIR", projects_dir):
            sessions = load_all_sessions()

        assert len(sessions) == 1
        assert sessions[0].session_id == "sess-aaa"
        assert sessions[0].project_path == "/Users/x/myproject"
        assert sessions[0].project_name == "myproject"

    def test_multiple_projects(self, tmp_path):
        projects_dir = tmp_path / "projects"
        _make_project(
            projects_dir,
            "-Users-x-alpha",
            "/Users/x/alpha",
            [{"sessionId": "s1", "modified": "2025-01-15T10:00:00Z"}],
        )
        _make_project(
            projects_dir,
            "-Users-x-beta",
            "/Users/x/beta",
            [{"sessionId": "s2", "modified": "2025-01-20T10:00:00Z"}],
        )
        with patch("ccui.data.PROJECTS_DIR", projects_dir):
            sessions = load_all_sessions()

        assert len(sessions) == 2
        # Sorted by modified time, newest first
        assert sessions[0].session_id == "s2"
        assert sessions[1].session_id == "s1"

    def test_picks_up_orphan_jsonl(self, tmp_path):
        """JSONL files not in the index should still be discovered."""
        projects_dir = tmp_path / "projects"
        proj_dir = projects_dir / "-Users-x-proj"
        proj_dir.mkdir(parents=True)

        # Index with one session
        (proj_dir / "sessions-index.json").write_text(
            json.dumps({"originalPath": "/Users/x/proj", "entries": []})
        )

        # Orphan JSONL not in index
        orphan = proj_dir / "orphan-sess.jsonl"
        orphan.write_text(
            json.dumps(
                {
                    "type": "user",
                    "timestamp": 1705312200000,
                    "message": {"content": "orphan msg"},
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "assistant",
                    "timestamp": 1705312260000,
                    "message": {"content": "response"},
                }
            )
            + "\n"
        )

        with patch("ccui.data.PROJECTS_DIR", projects_dir):
            sessions = load_all_sessions()

        assert len(sessions) == 1
        assert sessions[0].session_id == "orphan-sess"
        assert sessions[0].first_prompt == "orphan msg"

    def test_skips_hidden_dirs(self, tmp_path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        hidden = projects_dir / ".hidden"
        hidden.mkdir()
        (hidden / "sessions-index.json").write_text(
            '{"originalPath": "/x", "entries": [{"sessionId": "s1"}]}'
        )

        with patch("ccui.data.PROJECTS_DIR", projects_dir):
            sessions = load_all_sessions()

        assert len(sessions) == 0

    def test_empty_projects_dir(self, tmp_path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        with patch("ccui.data.PROJECTS_DIR", projects_dir):
            assert load_all_sessions() == []

    def test_missing_projects_dir(self, tmp_path):
        with patch("ccui.data.PROJECTS_DIR", tmp_path / "nope"):
            assert load_all_sessions() == []

    def test_deduplicates_indexed_and_orphan(self, tmp_path):
        """If a session is in both index and has a JSONL, don't double-count."""
        projects_dir = tmp_path / "projects"
        proj_dir = _make_project(
            projects_dir,
            "-Users-x-proj",
            "/Users/x/proj",
            [
                {
                    "sessionId": "s1",
                    "messages": [
                        {"type": "user", "message": {"content": "msg"}},
                    ],
                    "messageCount": 1,
                },
            ],
        )
        # s1.jsonl already exists from _make_project, so the glob will find it
        # but it should be deduplicated via indexed_sids
        with patch("ccui.data.PROJECTS_DIR", projects_dir):
            sessions = load_all_sessions()

        assert len(sessions) == 1
        assert sessions[0].session_id == "s1"

    def test_sorting_with_none_dates(self, tmp_path):
        """Sessions with None dates should sort to the end."""
        projects_dir = tmp_path / "projects"
        proj_dir = projects_dir / "-Users-x-proj"
        proj_dir.mkdir(parents=True)

        # Index with two sessions: one with date, one without
        (proj_dir / "sessions-index.json").write_text(
            json.dumps(
                {
                    "originalPath": "/Users/x/proj",
                    "entries": [
                        {
                            "sessionId": "with-date",
                            "modified": "2025-01-15T10:00:00Z",
                            "messageCount": 1,
                        },
                        {
                            "sessionId": "no-date",
                            "messageCount": 1,
                        },
                    ],
                }
            )
        )
        # Create minimal JSONL files
        (proj_dir / "with-date.jsonl").write_text("")
        (proj_dir / "no-date.jsonl").write_text("")

        with patch("ccui.data.PROJECTS_DIR", projects_dir):
            sessions = load_all_sessions()

        assert len(sessions) == 2
        # with-date should come first (newer), no-date last (datetime.min)
        assert sessions[0].session_id == "with-date"
        assert sessions[1].session_id == "no-date"

    def test_corrupt_index_falls_back_to_jsonl(self, tmp_path):
        """If sessions-index.json is corrupt, JSONL files should still load."""
        projects_dir = tmp_path / "projects"
        proj_dir = projects_dir / "-Users-x-proj"
        proj_dir.mkdir(parents=True)

        (proj_dir / "sessions-index.json").write_text("corrupt json!!!")

        # But there's a valid JSONL file
        (proj_dir / "valid-sess.jsonl").write_text(
            json.dumps(
                {
                    "type": "user",
                    "timestamp": 1705312200000,
                    "message": {"content": "still works"},
                }
            )
            + "\n"
        )

        with patch("ccui.data.PROJECTS_DIR", projects_dir):
            sessions = load_all_sessions()

        assert len(sessions) == 1
        assert sessions[0].session_id == "valid-sess"

    def test_no_index_file_scans_jsonl(self, tmp_path):
        """Project dir without sessions-index.json should scan JSONL files."""
        projects_dir = tmp_path / "projects"
        proj_dir = projects_dir / "-Users-x-proj"
        proj_dir.mkdir(parents=True)

        # No index file, just JSONL
        (proj_dir / "abc.jsonl").write_text(
            json.dumps(
                {
                    "type": "user",
                    "timestamp": 1705312200000,
                    "message": {"content": "no index"},
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "assistant",
                    "timestamp": 1705312260000,
                    "message": {"content": "reply"},
                }
            )
            + "\n"
        )

        with patch("ccui.data.PROJECTS_DIR", projects_dir):
            sessions = load_all_sessions()

        assert len(sessions) == 1
        assert sessions[0].first_prompt == "no index"
