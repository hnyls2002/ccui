"""Token usage tracking — aggregate and report Claude Code token consumption."""

from __future__ import annotations

import json
from pathlib import Path

from ccui.constants import CLAUDE_DIR, PROJECTS_DIR

USAGE_FILE = CLAUDE_DIR / "token-usage.json"
USAGE_SESSIONS_FILE = CLAUDE_DIR / "token-usage-sessions.json"


def _load_usage() -> dict:
    try:
        return json.loads(USAGE_FILE.read_text())
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return {}


def _load_tracked_sessions() -> dict[str, int]:
    """Load tracked sessions: {file_path: last_processed_byte_offset}."""
    try:
        data = json.loads(USAGE_SESSIONS_FILE.read_text())
        # Migrate from old set format (list of strings) to dict
        if isinstance(data, list):
            return {k: 0 for k in data}
        return data
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return {}


def _save_usage(data: dict) -> None:
    USAGE_FILE.write_text(json.dumps(data, indent=2, sort_keys=True))


def _save_tracked_sessions(tracked: dict[str, int]) -> None:
    USAGE_SESSIONS_FILE.write_text(json.dumps(tracked, sort_keys=True))


def _parse_date(ts: str | int | float) -> str:
    if isinstance(ts, str):
        return ts[:10]
    from datetime import datetime

    return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")


def aggregate_jsonl(jsonl_path: Path, data: dict, offset: int = 0) -> tuple[bool, int]:
    """Extract token usage from a JSONL file starting at byte offset.

    Returns (found_tokens, new_offset).
    """
    found = False
    new_offset = offset
    try:
        with open(jsonl_path) as f:
            if offset:
                f.seek(offset)
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message", {})
                usage = msg.get("usage", {})
                model = msg.get("model", "unknown")
                if not usage or model == "<synthetic>":
                    continue
                ts = obj.get("timestamp")
                if not ts:
                    continue
                date = _parse_date(ts)

                if date not in data:
                    data[date] = {}
                if model not in data[date]:
                    data[date][model] = [0, 0, 0, 0, 0]
                s = data[date][model]
                s[0] += usage.get("input_tokens", 0)
                s[1] += usage.get("output_tokens", 0)
                s[2] += usage.get("cache_read_input_tokens", 0)
                s[3] += usage.get("cache_creation_input_tokens", 0)
                s[4] += 1
                found = True
            new_offset = f.tell()
    except OSError:
        pass
    return found, new_offset


def sync_all_sessions() -> None:
    """Scan all existing session JSONL files, aggregate new/grown ones incrementally."""
    tracked = _load_tracked_sessions()
    data = _load_usage()
    changed = False

    # Find all JSONL files (main sessions + subagents)
    patterns = ["*/*.jsonl", "*/*/subagents/*.jsonl"]
    for pattern in patterns:
        for jsonl_path in PROJECTS_DIR.glob(pattern):
            key = str(jsonl_path)
            old_offset = tracked.get(key, 0)
            file_size = jsonl_path.stat().st_size
            if file_size <= old_offset:
                continue
            found, new_offset = aggregate_jsonl(jsonl_path, data, old_offset)
            if found:
                changed = True
            tracked[key] = new_offset

    if changed:
        _save_usage(data)
    _save_tracked_sessions(tracked)


def _fmt(n: int | float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _cost_for_model(model: str, s: list) -> float:
    """Calculate API-equivalent cost for a model's token counts."""
    if "opus" in model:
        return (s[0] * 15 + s[1] * 75 + s[2] * 1.5 + s[3] * 18.75) / 1e6
    if "haiku" in model:
        return (s[0] * 0.8 + s[1] * 4 + s[2] * 0.08 + s[3] * 1.0) / 1e6
    return (s[0] * 3 + s[1] * 15 + s[2] * 0.3 + s[3] * 3.75) / 1e6


def _bar(value: float, max_value: float, width: int = 20) -> str:
    """Render a simple bar chart."""
    if max_value <= 0:
        return ""
    filled = int(value / max_value * width)
    return "█" * filled + "░" * (width - filled)


def print_usage(days: int = 10) -> None:
    """Print daily token usage stats to stdout."""
    data = _load_usage()
    if not data:
        print("No token usage data found.")
        return

    dates = sorted(data.keys())[-days:]

    # Pre-compute per-day stats
    rows = []
    for date in dates:
        models = data[date]
        output = sum(v[1] for v in models.values())
        msgs = sum(v[4] for v in models.values())
        cost = sum(_cost_for_model(m, s) for m, s in models.items())
        rows.append((date, msgs, output, cost))

    max_cost = max(r[3] for r in rows) if rows else 1

    # Header
    print("  Date       Msgs   Output      Cost   ")
    print("  ─────────  ─────  ──────  ─────────  " + "─" * 20)

    grand_msgs = 0
    grand_output = 0
    grand_cost = 0.0

    for date, msgs, output, cost in rows:
        grand_msgs += msgs
        grand_output += output
        grand_cost += cost
        bar = _bar(cost, max_cost)
        print("  %s  %5d  %6s  $%7.2f  %s" % (date, msgs, _fmt(output), cost, bar))

    print("  ─────────  ─────  ──────  ─────────  " + "─" * 20)
    print(
        "  TOTAL      %5d  %6s  $%7.2f" % (grand_msgs, _fmt(grand_output), grand_cost)
    )
