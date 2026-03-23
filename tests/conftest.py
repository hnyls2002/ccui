"""Shared fixtures for ccui tests."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from ccui.data import SessionInfo


@pytest.fixture()
def tmp_session(tmp_path: Path) -> SessionInfo:
    """Create a minimal SessionInfo pointing to tmp_path."""
    jsonl = tmp_path / "abc123.jsonl"
    jsonl.write_text("")
    return SessionInfo(
        session_id="abc123",
        project_path="/Users/x/myproject",
        project_name="myproject",
        first_prompt="hello",
        slug="hello-world",
        custom_title="Hello World",
        message_count=5,
        created=datetime(2025, 1, 15, 10, 0),
        modified=datetime(2025, 1, 15, 12, 0),
        git_branch="main",
        jsonl_path=jsonl,
    )


@pytest.fixture()
def write_jsonl(tmp_path: Path):
    """Helper to write a JSONL file with given objects."""

    def _write(filename: str, objects: list[dict]) -> Path:
        p = tmp_path / filename
        lines = [json.dumps(obj) for obj in objects]
        p.write_text("\n".join(lines) + "\n")
        return p

    return _write
