"""Tests for ccui.archive — archive load/save/toggle."""

from __future__ import annotations

import json
from unittest.mock import patch

from ccui import archive


class TestArchive:
    def _patch_file(self, tmp_path):
        return patch.object(archive, "ARCHIVE_FILE", tmp_path / "archives.json")

    def test_load_empty(self, tmp_path):
        with self._patch_file(tmp_path):
            assert archive.get_archived_ids() == set()

    def test_save_and_load(self, tmp_path):
        with self._patch_file(tmp_path):
            archive._save({"s1", "s2"})
            result = archive.get_archived_ids()
            assert result == {"s1", "s2"}

    def test_toggle_archive_on(self, tmp_path):
        with self._patch_file(tmp_path):
            result = archive.toggle_archive("s1")
            assert result is True
            assert archive.is_archived("s1")

    def test_toggle_archive_off(self, tmp_path):
        with self._patch_file(tmp_path):
            archive.toggle_archive("s1")  # on
            result = archive.toggle_archive("s1")  # off
            assert result is False
            assert not archive.is_archived("s1")

    def test_is_archived_false(self, tmp_path):
        with self._patch_file(tmp_path):
            assert not archive.is_archived("nonexistent")

    def test_corrupt_json(self, tmp_path):
        with self._patch_file(tmp_path):
            (tmp_path / "archives.json").write_text("not json")
            assert archive.get_archived_ids() == set()

    def test_wrong_json_type(self, tmp_path):
        # array (legacy) and dict (new format) are both valid; anything else returns empty
        with self._patch_file(tmp_path):
            (tmp_path / "archives.json").write_text(json.dumps("not-a-container"))
            assert archive.get_archived_ids() == set()

    def test_load_dict_format(self, tmp_path):
        # New format: {"<sid>": {"summary": "..."}}; keys are the archived SIDs
        with self._patch_file(tmp_path):
            (tmp_path / "archives.json").write_text(
                json.dumps({"s1": {"summary": "x"}, "s2": {"summary": "y"}})
            )
            assert archive.get_archived_ids() == {"s1", "s2"}

    def test_save_format(self, tmp_path):
        with self._patch_file(tmp_path):
            archive._save({"b", "a"})
            data = json.loads((tmp_path / "archives.json").read_text())
            assert data == ["a", "b"]  # sorted
