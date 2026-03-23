"""Tests for _dir_name_to_project_path — greedy segment merging with real filesystem."""

from __future__ import annotations

from pathlib import Path

from ccui.data import _dir_name_to_project_path


class TestDirNameToProjectPath:
    def test_simple_path(self, tmp_path):
        """Simple path with no special chars: /a/b/c encoded as -a-b-c."""
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "b").mkdir()
        (tmp_path / "a" / "b" / "c").mkdir()

        # Encoded: "-a-b-c" but _dir_name_to_project_path starts from /
        # We need a path that actually exists. Let's use tmp_path structure.
        # The function walks from / and checks os.path.exists, so we need
        # to test with paths that exist on the actual filesystem.

        # Test with a known real path
        home = str(Path.home())
        parts = home.lstrip("/").split("/")
        encoded = "-".join(parts)
        result = _dir_name_to_project_path(encoded)
        assert result == home

    def test_path_with_underscore(self, tmp_path):
        """Directory names with underscores: my_project -> my-project in encoding.

        The function tries to merge adjacent segments with _ separator.
        """
        # Create /tmp/xxx/my_project
        proj = tmp_path / "my_project"
        proj.mkdir()

        # The encoded name would have tmp_path parts + "my-project"
        # But _dir_name_to_project_path starts from /, so we need the full path
        tmp_parts = str(tmp_path).lstrip("/").split("/")
        encoded = "-".join(tmp_parts) + "-my-project"
        result = _dir_name_to_project_path(encoded)
        assert result == str(proj), f"Expected {proj}, got {result}"

    def test_path_with_dot_prefix(self, tmp_path):
        """Dot-prefixed dirs like .claude produce -- in encoding."""
        dot_dir = tmp_path / ".hidden"
        dot_dir.mkdir()

        tmp_parts = str(tmp_path).lstrip("/").split("/")
        # "--hidden" represents ".hidden" (empty segment from -- means dot prefix)
        encoded = "-".join(tmp_parts) + "--hidden"
        result = _dir_name_to_project_path(encoded)
        assert result == str(dot_dir), f"Expected {dot_dir}, got {result}"

    def test_nonexistent_path_falls_back(self):
        """Non-existent segments are used as-is in the path."""
        result = _dir_name_to_project_path("-nonexistent-path-here")
        assert result == "/nonexistent/path/here"

    def test_empty_after_lstrip(self):
        """Input '---' after lstrip('-') becomes '', split gives ['']."""
        result = _dir_name_to_project_path("---")
        # lstrip("-") -> "", split("-") -> [""]
        # segment = "" + parts[0] = "" (dot_prefix="" since parts[0]="" but
        # actually i=0, parts[0]="" but the condition parts[i]=="" and i+1 < len
        # is False since len(parts)=1, so dot_prefix="" and segment=""
        assert isinstance(result, str)  # should not crash

    def test_hyphenated_dir_name(self, tmp_path):
        """Dir name with hyphens: my-app -> needs merge with - separator."""
        app_dir = tmp_path / "my-app"
        app_dir.mkdir()

        tmp_parts = str(tmp_path).lstrip("/").split("/")
        # "my-app" encodes as "my-app" which splits to ["my", "app"]
        # The function should try merging with "-" and find the directory
        encoded = "-".join(tmp_parts) + "-my-app"
        result = _dir_name_to_project_path(encoded)
        assert result == str(app_dir), f"Expected {app_dir}, got {result}"

    def test_multiple_underscores(self, tmp_path):
        """Dir with multiple underscores: my_cool_project."""
        proj = tmp_path / "my_cool_project"
        proj.mkdir()

        tmp_parts = str(tmp_path).lstrip("/").split("/")
        encoded = "-".join(tmp_parts) + "-my-cool-project"
        result = _dir_name_to_project_path(encoded)
        assert result == str(proj), f"Expected {proj}, got {result}"

    def test_nested_special_dirs(self, tmp_path):
        """Nested dirs with mixed special chars."""
        inner = tmp_path / "my_app" / ".config"
        inner.mkdir(parents=True)

        tmp_parts = str(tmp_path).lstrip("/").split("/")
        # my_app encodes as "my-app", .config encodes as "-config" (-- for dot)
        encoded = "-".join(tmp_parts) + "-my-app--config"
        result = _dir_name_to_project_path(encoded)
        assert result == str(inner), f"Expected {inner}, got {result}"
