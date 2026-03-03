# ccui

TUI for browsing and managing Claude Code sessions, plans, notes, and project config.

## Install

```bash
pip install -e .
```

## Usage

```bash
ccui
```

## Views

`Tab` switches between two views:

### Timeline View (default)

All sessions across projects, sorted by most recent:

```
 Project     │ Title                     │ Msgs │ Date    │
 ────────────┼───────────────────────────┼──────┼─────────┼─────
▸ my-project │ refactor auth module      │  42  │ Feb 28  │
  another    │ add TUI dashboard         │ 120  │ Mar 02  │
  my-project │ fix streaming bug         │  93  │ Mar 01  │ [A]
```

### Project View

Left: project list. Right: 4 tabs — Sessions, Plans, Notes, Config.

```
  Projects       ║  [Sessions]  Plans  Notes  Config
  ─────────      ║  ──────────────────────────────────
▸ my-project (15)║  Title                     │ Msgs │ Date
  another    (6) ║▸ refactor auth module      │  42  │ Feb 28
  side-proj  (1) ║  fix streaming bug         │  93  │ Mar 01
```

Switch tabs with `1` `2` `3` `4`.

## Keybindings

| Key | Action |
|-----|--------|
| `j` / `k` or `↑` / `↓` | Navigate up/down |
| `Enter` or `l` | View session detail / plan / note |
| `Tab` | Switch Timeline ↔ Project view |
| `1` `2` `3` `4` | Switch to Sessions / Plans / Notes / Config tab |
| `d` | Delete session / plan / note |
| `a` | Toggle archive on session |
| `H` (shift+h) | Toggle show/hide archived sessions |
| `r` | Rename session title / plan / note |
| `n` | New plan or note (opens `$EDITOR`) |
| `e` | Edit plan / note / CLAUDE.md in `$EDITOR` |
| `x` | Export session as plan or note |
| `/` | Search / filter |
| `g` / `G` | Jump to top / bottom |
| `q` | Quit |
| `Esc` | Back / close search |

## Features

### Session Management

- Browse all Claude Code sessions across projects
- Preview first few messages inline
- Custom titles (`r` to rename, stored in `~/.claude/session-titles.json`)
- Archive sessions (`a` to toggle, `H` to show/hide archived)
- Delete sessions with confirmation

### Plans & Notes

Stored in `{project}/.claude/plans/*.md` and `{project}/.claude/notes/*.md`.

Each file has YAML frontmatter:

```yaml
---
title: refactor auth module
created: 2025-03-01
session: a1b2c3d4-...   # optional, linked session id
---
```

- `n` to create new (opens in `$EDITOR`)
- `e` to edit existing
- `x` to export a session conversation as a plan or note
- Plans can link to a session — shows `→ session title` in the list

### Project Config

The Config tab shows a read-only overview of a project's Claude Code configuration:

- **CLAUDE.md** — existence and line count
- **Auto Memory** — MEMORY.md status and topic files
- **settings.local.json** — permission rule count
- **Rules** (`.claude/rules/`) — rule files and their path scopes
- **Skills** — project-level and global skills

## Data Locations

| Data | Location |
|------|----------|
| Sessions | `~/.claude/projects/{project}/*.jsonl` (Claude Code native) |
| Plans | `{project}/.claude/plans/*.md` |
| Notes | `{project}/.claude/notes/*.md` |
| Session titles | `~/.claude/session-titles.json` |
| Archive state | `~/.claude/session-archives.json` |

## Project Structure

```
src/ccui/
├── app.py        # Textual TUI
├── data.py       # Session scanning and parsing
├── archive.py    # Archive state management
├── titles.py     # Custom session titles
├── notes.py      # Plan/note CRUD
└── config.py     # Project config scanning (CLAUDE.md, rules, memory, skills, settings)
```
