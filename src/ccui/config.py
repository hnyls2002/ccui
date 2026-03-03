"""Scan Claude Code project and global config: CLAUDE.md, rules, memory, skills, settings."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SkillInfo:
    name: str
    description: str
    path: Path
    is_global: bool


@dataclass
class RuleInfo:
    name: str  # filename without .md
    paths: list[str]  # path scope from frontmatter, empty = global
    path: Path  # file path
    is_global: bool


@dataclass
class MemoryInfo:
    memory_md_lines: int  # 0 if not found
    topic_files: list[str]  # filenames of extra topic files
    memory_dir: Path


@dataclass
class ConfigInfo:
    """Full config for a project or global scope."""

    scope: str  # "project" or "global"
    base_path: Path  # project root or ~/.claude

    # CLAUDE.md
    claude_md_path: Path | None
    claude_md_lines: int

    # Rules
    rules: list[RuleInfo]

    # Skills
    skills: list[SkillInfo]

    # Memory (project only)
    memory: MemoryInfo | None

    # Settings
    settings_path: Path | None
    permission_count: int


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text()
    except OSError:
        return {}
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    fm: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^(\w[\w-]*)\s*:\s*(.+)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip("\"'")
    return fm


def _count_lines(path: Path) -> int:
    try:
        return len(path.read_text().splitlines())
    except OSError:
        return 0


def _count_permissions(settings_path: Path) -> int:
    if not settings_path.exists():
        return 0
    try:
        data = json.loads(settings_path.read_text())
        return len(data.get("permissions", {}).get("allow", []))
    except (json.JSONDecodeError, OSError):
        return 0


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


def _scan_skills(skills_dir: Path, is_global: bool) -> list[SkillInfo]:
    skills: list[SkillInfo] = []
    if not skills_dir.exists():
        return skills
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        fm = _parse_frontmatter(skill_md)
        skills.append(
            SkillInfo(
                name=fm.get("name", skill_dir.name),
                description=fm.get("description", ""),
                path=skill_md,
                is_global=is_global,
            )
        )
    return skills


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _scan_rules(rules_dir: Path, is_global: bool) -> list[RuleInfo]:
    rules: list[RuleInfo] = []
    if not rules_dir.exists():
        return rules
    for md_file in sorted(rules_dir.glob("*.md")):
        fm = _parse_frontmatter(md_file)
        paths_str = fm.get("paths", "")
        paths = (
            [p.strip() for p in paths_str.split(",") if p.strip()] if paths_str else []
        )
        rules.append(
            RuleInfo(
                name=md_file.stem,
                paths=paths,
                path=md_file,
                is_global=is_global,
            )
        )
    return rules


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def _scan_memory(project_path: str) -> MemoryInfo | None:
    """Scan auto memory for a project."""
    # Memory is stored in ~/.claude/projects/{encoded}/memory/
    encoded = project_path.replace("/", "-")
    memory_dir = CLAUDE_DIR / "projects" / encoded / "memory"
    if not memory_dir.exists():
        return MemoryInfo(memory_md_lines=0, topic_files=[], memory_dir=memory_dir)

    memory_md = memory_dir / "MEMORY.md"
    lines = _count_lines(memory_md) if memory_md.exists() else 0
    topic_files = [
        f.name for f in sorted(memory_dir.glob("*.md")) if f.name != "MEMORY.md"
    ]

    return MemoryInfo(
        memory_md_lines=lines, topic_files=topic_files, memory_dir=memory_dir
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_project_config(project_path: str) -> ConfigInfo:
    """Get full config for a project."""
    p = Path(project_path)

    # CLAUDE.md — check both locations
    claude_md = None
    for candidate in [p / "CLAUDE.md", p / ".claude" / "CLAUDE.md"]:
        if candidate.exists():
            claude_md = candidate
            break

    return ConfigInfo(
        scope="project",
        base_path=p,
        claude_md_path=claude_md,
        claude_md_lines=_count_lines(claude_md) if claude_md else 0,
        rules=_scan_rules(p / ".claude" / "rules", is_global=False),
        skills=_scan_skills(p / ".claude" / "skills", is_global=False),
        memory=_scan_memory(project_path),
        settings_path=(
            p / ".claude" / "settings.local.json"
            if (p / ".claude" / "settings.local.json").exists()
            else None
        ),
        permission_count=_count_permissions(p / ".claude" / "settings.local.json"),
    )


def get_global_config() -> ConfigInfo:
    """Get global Claude Code config."""
    claude_md = CLAUDE_DIR / "CLAUDE.md"

    return ConfigInfo(
        scope="global",
        base_path=CLAUDE_DIR,
        claude_md_path=claude_md if claude_md.exists() else None,
        claude_md_lines=_count_lines(claude_md) if claude_md.exists() else 0,
        rules=_scan_rules(CLAUDE_DIR / "rules", is_global=True),
        skills=_scan_skills(CLAUDE_DIR / "skills", is_global=True),
        memory=None,
        settings_path=(
            CLAUDE_DIR / "settings.json"
            if (CLAUDE_DIR / "settings.json").exists()
            else None
        ),
        permission_count=_count_permissions(CLAUDE_DIR / "settings.json"),
    )


def read_file_content(path: Path) -> str:
    """Read file content."""
    try:
        return path.read_text()
    except OSError:
        return "(failed to read)"


def create_skill(project_path: str, name: str, description: str) -> SkillInfo:
    """Create a new project-level skill."""
    skill_dir = Path(project_path) / ".claude" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{description}\n\n## Instructions\n\n(Add your skill instructions here)\n"
    )
    return SkillInfo(name=name, description=description, path=skill_md, is_global=False)


def delete_skill(skill: SkillInfo) -> bool:
    """Delete a project-level skill directory."""
    if skill.is_global:
        return False
    import shutil

    shutil.rmtree(skill.path.parent, ignore_errors=True)
    return True


def delete_rule(rule: RuleInfo) -> bool:
    """Delete a rule file."""
    if rule.is_global:
        return False
    try:
        if rule.path.exists():
            rule.path.unlink()
        return True
    except OSError:
        return False
