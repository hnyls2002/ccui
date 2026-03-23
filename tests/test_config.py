"""Tests for ccui.config — parsing, scanning, skill/rule CRUD."""

from __future__ import annotations

import json
from pathlib import Path

from ccui.config import (
    RuleInfo,
    SkillInfo,
    _count_lines,
    _parse_frontmatter,
    _read_permissions,
    _scan_rules,
    _scan_skills,
    create_skill,
    delete_rule,
    delete_skill,
    read_file_content,
)

# ── _parse_frontmatter ──────────────────────────────────────────────


class TestParseFrontmatter:
    def test_basic(self, tmp_path):
        p = tmp_path / "rule.md"
        p.write_text("---\nname: my-rule\ndescription: A rule\n---\nBody\n")
        fm = _parse_frontmatter(p)
        assert fm["name"] == "my-rule"
        assert fm["description"] == "A rule"

    def test_strips_quotes(self, tmp_path):
        p = tmp_path / "q.md"
        p.write_text("---\nname: 'quoted'\n---\n")
        fm = _parse_frontmatter(p)
        assert fm["name"] == "quoted"

    def test_hyphenated_keys(self, tmp_path):
        p = tmp_path / "h.md"
        p.write_text("---\nmy-key: value\n---\n")
        fm = _parse_frontmatter(p)
        assert fm["my-key"] == "value"

    def test_no_frontmatter(self, tmp_path):
        p = tmp_path / "plain.md"
        p.write_text("# Just markdown\n")
        assert _parse_frontmatter(p) == {}

    def test_missing_file(self, tmp_path):
        assert _parse_frontmatter(tmp_path / "nope.md") == {}


# ── _count_lines ─────────────────────────────────────────────────────


class TestCountLines:
    def test_counts(self, tmp_path):
        p = tmp_path / "f.txt"
        p.write_text("line1\nline2\nline3\n")
        assert _count_lines(p) == 3

    def test_missing_file(self, tmp_path):
        assert _count_lines(tmp_path / "nope") == 0

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty"
        p.write_text("")
        assert _count_lines(p) == 0


# ── _read_permissions ────────────────────────────────────────────────


class TestReadPermissions:
    def test_reads_allow(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"permissions": {"allow": ["Bash(*)", "Read(*)"]}}))
        assert _read_permissions(p) == ["Bash(*)", "Read(*)"]

    def test_missing_file(self, tmp_path):
        assert _read_permissions(tmp_path / "nope.json") == []

    def test_no_permissions_key(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"theme": "dark"}))
        assert _read_permissions(p) == []

    def test_corrupt_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json")
        assert _read_permissions(p) == []


# ── _scan_skills ─────────────────────────────────────────────────────


class TestScanSkills:
    def test_scans_directory(self, tmp_path):
        skill_dir = tmp_path / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A skill\n---\nBody\n"
        )
        skills = _scan_skills(tmp_path / "skills", is_global=False)
        assert len(skills) == 1
        assert skills[0].name == "my-skill"
        assert skills[0].description == "A skill"
        assert skills[0].is_global is False

    def test_empty_dir(self, tmp_path):
        d = tmp_path / "skills"
        d.mkdir()
        assert _scan_skills(d, is_global=True) == []

    def test_missing_dir(self, tmp_path):
        assert _scan_skills(tmp_path / "nope", is_global=True) == []

    def test_skips_non_skill_dirs(self, tmp_path):
        d = tmp_path / "skills"
        d.mkdir()
        # Directory without SKILL.md
        (d / "not-a-skill").mkdir()
        (d / "not-a-skill" / "readme.md").write_text("hi")
        # File, not directory
        (d / "file.txt").write_text("hi")
        assert _scan_skills(d, is_global=True) == []


# ── _scan_rules ──────────────────────────────────────────────────────


class TestScanRules:
    def test_scans_rules(self, tmp_path):
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        (rules_dir / "style.md").write_text(
            "---\npaths: src/**, tests/**\n---\nStyle rules\n"
        )
        rules = _scan_rules(rules_dir, is_global=False)
        assert len(rules) == 1
        assert rules[0].name == "style"
        assert rules[0].paths == ["src/**", "tests/**"]

    def test_no_paths(self, tmp_path):
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        (rules_dir / "global.md").write_text("---\n---\nGlobal rule\n")
        rules = _scan_rules(rules_dir, is_global=True)
        assert len(rules) == 1
        assert rules[0].paths == []
        assert rules[0].is_global is True

    def test_missing_dir(self, tmp_path):
        assert _scan_rules(tmp_path / "nope", is_global=True) == []


# ── create_skill / delete_skill ──────────────────────────────────────


class TestCreateDeleteSkill:
    def test_create_skill(self, tmp_path):
        skill = create_skill(str(tmp_path), "test-skill", "A test skill")
        assert skill.name == "test-skill"
        assert skill.path.exists()
        content = skill.path.read_text()
        assert "name: test-skill" in content
        assert "description: A test skill" in content

    def test_delete_skill(self, tmp_path):
        skill = create_skill(str(tmp_path), "del-me", "delete me")
        assert skill.path.parent.exists()
        assert delete_skill(skill) is True
        assert not skill.path.parent.exists()

    def test_delete_global_skill_refused(self):
        skill = SkillInfo(
            name="g",
            description="",
            path=Path("/fake/SKILL.md"),
            is_global=True,
        )
        assert delete_skill(skill) is False


# ── delete_rule ──────────────────────────────────────────────────────


class TestDeleteRule:
    def test_delete_rule(self, tmp_path):
        p = tmp_path / "rule.md"
        p.write_text("content")
        rule = RuleInfo(name="rule", paths=[], path=p, is_global=False)
        assert delete_rule(rule) is True
        assert not p.exists()

    def test_delete_global_rule_refused(self):
        rule = RuleInfo(
            name="g",
            paths=[],
            path=Path("/fake/rule.md"),
            is_global=True,
        )
        assert delete_rule(rule) is False

    def test_delete_already_missing(self, tmp_path):
        rule = RuleInfo(
            name="ghost",
            paths=[],
            path=tmp_path / "ghost.md",
            is_global=False,
        )
        assert delete_rule(rule) is True


# ── read_file_content ────────────────────────────────────────────────


class TestReadFileContent:
    def test_reads(self, tmp_path):
        p = tmp_path / "f.txt"
        p.write_text("hello")
        assert read_file_content(p) == "hello"

    def test_missing(self, tmp_path):
        assert read_file_content(tmp_path / "nope") == "(failed to read)"
