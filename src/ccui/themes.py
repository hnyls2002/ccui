"""Theme definitions and persistence."""

from __future__ import annotations

import json

from textual.theme import Theme

from ccui.constants import CLAUDE_DIR

CCUI_CONFIG = CLAUDE_DIR / "ccui.json"

# ── Custom themes ──────────────────────────────────────────────────────

QUIET_LIGHT = Theme(
    name="quiet-light",
    primary="#4B69C6",
    secondary="#7B8794",
    accent="#4B83CD",
    foreground="#333333",
    background="#F5F5F5",
    surface="#EBEBEB",
    panel="#E0E0E0",
    success="#448C27",
    warning="#C18401",
    error="#C4265E",
    dark=False,
)

CUSTOM_THEMES: list[Theme] = [QUIET_LIGHT]

# ── Theme cycle order ──────────────────────────────────────────────────

THEME_CYCLE = [
    "quiet-light",
    "textual-light",
    "catppuccin-latte",
    "solarized-light",
    "textual-dark",
    "nord",
    "dracula",
    "tokyo-night",
    "gruvbox",
    "catppuccin-mocha",
]


# ── Config persistence ─────────────────────────────────────────────────


def load_theme_name() -> str:
    """Load saved theme name from config."""
    try:
        data = json.loads(CCUI_CONFIG.read_text())
        return data.get("theme", "quiet-light")
    except (OSError, json.JSONDecodeError):
        return "quiet-light"


def save_theme_name(name: str) -> None:
    """Save theme name to config."""
    data: dict = {}
    try:
        data = json.loads(CCUI_CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        pass
    data["theme"] = name
    CCUI_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CCUI_CONFIG.write_text(json.dumps(data, indent=2) + "\n")
