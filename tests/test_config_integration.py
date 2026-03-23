"""Tests for config.get_project_config / get_global_config with real filesystem."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from ccui.config import get_global_config, get_project_config


def _setup_project(tmp_path: Path) -> str:
    """Create a realistic project structure. Returns project path."""
    proj = tmp_path / "myproject"
    proj.mkdir()
    claude_dir = proj / ".claude"
    claude_dir.mkdir()

    # CLAUDE.md
    (proj / "CLAUDE.md").write_text("# Instructions\n\nDo stuff\n")

    # Rules
    rules_dir = claude_dir / "rules"
    rules_dir.mkdir()
    (rules_dir / "style.md").write_text(
        "---\npaths: src/**, tests/**\n---\nStyle guide\n"
    )
    (rules_dir / "security.md").write_text("---\n---\nSecurity rules\n")

    # Skills
    skill_dir = claude_dir / "skills" / "test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: A test skill\n---\nBody\n"
    )

    # Settings
    (claude_dir / "settings.local.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(*)", "Read(*)"]}})
    )

    return str(proj)


class TestGetProjectConfig:
    def test_full_config(self, tmp_path):
        proj_path = _setup_project(tmp_path)
        config = get_project_config(proj_path)

        assert config.scope == "project"
        assert config.claude_md_path is not None
        assert config.claude_md_lines > 0
        assert len(config.rules) == 2
        assert len(config.skills) == 1
        assert config.skills[0].name == "test-skill"
        assert config.permission_count == 2
        assert "Bash(*)" in config.permission_rules
        assert config.settings_path is not None

    def test_claude_md_in_dot_claude(self, tmp_path):
        """CLAUDE.md inside .claude/ should be found if not in project root."""
        proj = tmp_path / "proj"
        proj.mkdir()
        claude_dir = proj / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("# Alt location\n")

        config = get_project_config(str(proj))
        assert config.claude_md_path is not None
        assert ".claude/CLAUDE.md" in str(config.claude_md_path)

    def test_empty_project(self, tmp_path):
        """Project with no .claude dir at all."""
        proj = tmp_path / "empty"
        proj.mkdir()
        config = get_project_config(str(proj))

        assert config.claude_md_path is None
        assert config.claude_md_lines == 0
        assert config.rules == []
        assert config.skills == []
        assert config.permission_count == 0
        assert config.settings_path is None

    def test_rules_parse_paths(self, tmp_path):
        proj_path = _setup_project(tmp_path)
        config = get_project_config(proj_path)

        style_rule = next(r for r in config.rules if r.name == "style")
        assert style_rule.paths == ["src/**", "tests/**"]
        assert style_rule.is_global is False

        security_rule = next(r for r in config.rules if r.name == "security")
        assert security_rule.paths == []

    def test_memory_scanning(self, tmp_path):
        """Memory dir should be scanned if it exists."""
        proj_path = _setup_project(tmp_path)
        config = get_project_config(proj_path)
        # Memory is in ~/.claude/projects/{encoded}/memory/
        # Our tmp project won't have real memory, so it should be empty or None
        if config.memory is not None:
            assert isinstance(config.memory.topic_files, list)


class TestGetGlobalConfig:
    def test_with_real_claude_dir(self, tmp_path):
        """Test with a simulated ~/.claude directory."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("# Global\nInstructions\n")

        rules_dir = claude_dir / "rules"
        rules_dir.mkdir()
        (rules_dir / "global-rule.md").write_text("---\n---\nGlobal rule\n")

        skills_dir = claude_dir / "skills" / "global-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: global-skill\ndescription: Global\n---\n"
        )

        (claude_dir / "settings.json").write_text(
            json.dumps({"permissions": {"allow": ["Bash(git *)"]}})
        )

        with patch("ccui.config.CLAUDE_DIR", claude_dir):
            config = get_global_config()

        assert config.scope == "global"
        assert config.claude_md_path is not None
        assert config.claude_md_lines == 2
        assert len(config.rules) == 1
        assert config.rules[0].is_global is True
        assert len(config.skills) == 1
        assert config.skills[0].is_global is True
        assert config.permission_count == 1
        assert config.memory is None  # global has no memory

    def test_empty_claude_dir(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        with patch("ccui.config.CLAUDE_DIR", claude_dir):
            config = get_global_config()

        assert config.claude_md_path is None
        assert config.rules == []
        assert config.skills == []
        assert config.permission_count == 0

    def test_corrupt_settings(self, tmp_path):
        """Corrupt settings.json should not crash, just return 0 permissions."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text("not json")

        with patch("ccui.config.CLAUDE_DIR", claude_dir):
            config = get_global_config()

        assert config.permission_count == 0
        assert config.permission_rules == []
