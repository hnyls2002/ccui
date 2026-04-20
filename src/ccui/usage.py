"""Token usage tracking — aggregate and report Claude Code token consumption."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ccui.constants import CLAUDE_DIR, PROJECTS_DIR

USAGE_FILE = CLAUDE_DIR / "token-usage.json"
USAGE_SESSIONS_FILE = CLAUDE_DIR / "token-usage-sessions.json"
QUOTA_CACHE_TTL = 60  # seconds


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


def _parse_date_hour(ts: str | int | float) -> tuple[str, str]:
    """Return (YYYY-MM-DD, HH) for a timestamp, in UTC."""
    if isinstance(ts, str):
        return ts[:10], ts[11:13]
    from datetime import datetime, timezone

    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H")


def _is_old_format(data: dict) -> bool:
    """Detect pre-hour schema: data[date][model] = list instead of data[date][hour][model] = list."""
    for entries in data.values():
        if not isinstance(entries, dict):
            return True
        for v in entries.values():
            return isinstance(v, list)
    return False


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
                date, hour = _parse_date_hour(ts)

                if date not in data:
                    data[date] = {}
                if hour not in data[date]:
                    data[date][hour] = {}
                if model not in data[date][hour]:
                    data[date][hour][model] = [0, 0, 0, 0, 0]
                s = data[date][hour][model]
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
    data = _load_usage()
    migrated = _is_old_format(data)
    if migrated:
        data = {}
        _save_tracked_sessions({})  # reset offsets to re-scan everything
    tracked = _load_tracked_sessions()
    changed = migrated

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


def _get_oauth_token() -> str | None:
    """Extract OAuth access token from macOS Keychain."""
    try:
        raw = subprocess.check_output(
            [
                "security",
                "find-generic-password",
                "-s",
                "Claude Code-credentials",
                "-w",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return json.loads(raw).get("claudeAiOauth", {}).get("accessToken")
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
        return None


def _quota_cache_file() -> Path:
    """Return account-specific cache file path based on current token hash."""
    import hashlib

    token = _get_oauth_token()
    if not token:
        return CLAUDE_DIR / "quota-cache.json"
    h = hashlib.sha256(token.encode()).hexdigest()[:8]
    return CLAUDE_DIR / f"quota-cache-{h}.json"


def _load_quota_cache() -> dict | None:
    """Load cached quota if still fresh (within TTL)."""
    import time

    try:
        cache = json.loads(_quota_cache_file().read_text())
        if time.time() - cache.get("ts", 0) < QUOTA_CACHE_TTL:
            return cache.get("data")
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        pass
    return None


def _save_quota_cache(data: dict) -> None:
    import time

    _quota_cache_file().write_text(json.dumps({"ts": time.time(), "data": data}))


def fetch_quota() -> dict | None:
    """Fetch subscription quota, with 60s disk cache."""
    cached = _load_quota_cache()
    if cached is not None:
        return cached

    import urllib.error
    import urllib.request

    token = _get_oauth_token()
    if not token:
        return None
    req = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            _save_quota_cache(data)
            return data
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None


def _format_reset(resets_at: str | None) -> str:
    if not resets_at:
        return ""
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(resets_at)
        delta = dt - datetime.now(timezone.utc)
        hours = int(delta.total_seconds() // 3600)
        mins = int((delta.total_seconds() % 3600) // 60)
        return f"{hours}h{mins:02d}m" if hours > 0 else f"{mins}m"
    except (ValueError, TypeError):
        return ""


BOX_INNER = 51  # fixed inner width for quota box


def _quota_row(label: str, pct: float, resets_at: str | None, width: int = 20) -> str:
    filled = int(pct / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    reset = _format_reset(resets_at)
    reset_part = f"~ {reset}" if reset else ""
    content = f"{label:<12s} {bar} {pct:5.1f}%  {reset_part}"
    return f"  │  {content:<{BOX_INNER}s}│"


def print_quota(show_extra: bool = False, file: Any = None) -> None:
    """Print subscription quota section."""
    from functools import partial

    p = partial(print, file=file)

    quota = fetch_quota()
    if not quota:
        p("  (quota unavailable)")
        return

    rows = []
    for key, label in [
        ("five_hour", "5h window"),
        ("seven_day", "7d window"),
        ("seven_day_sonnet", "7d sonnet"),
    ]:
        entry = quota.get(key)
        if entry and entry.get("utilization") is not None:
            rows.append(_quota_row(label, entry["utilization"], entry.get("resets_at")))

    if show_extra:
        extra = quota.get("extra_usage")
        if extra and extra.get("is_enabled"):
            used = (extra.get("used_credits") or 0) / 100  # cents → dollars
            limit = (extra.get("monthly_limit") or 0) / 100
            pct = extra.get("utilization")
            if pct is None:
                pct = (used / limit * 100) if limit > 0 else 0.0
            rows.append(_quota_row(f"extra ${used:.0f}", pct, None))

    if not rows:
        return

    bw = BOX_INNER + 2  # +2 for "  " padding inside │
    p(f"  ╭{'─ Quota ':─<{bw}}╮")
    for r in rows:
        p(r)
    p(f"  ╰{'─' * bw}╯")


def _day_stats(day: dict) -> tuple[int, int, int, int, float]:
    """Aggregate one day's {hour: {model: [i,o,cr,cw,msgs]}} into (inp, cached, output, msgs, cost)."""
    inp = cached = output = msgs = 0
    cost = 0.0
    for hour_data in day.values():
        for model, s in hour_data.items():
            inp += s[0]
            output += s[1]
            cached += s[2]
            msgs += s[4]
            cost += _cost_for_model(model, s)
    return inp, cached, output, msgs, cost


def _render_vertical_bars(
    values: list[float], height: int = 6, width: int = 2
) -> list[str]:
    """Render values as a height-row vertical bar chart, `width` chars per value."""
    if not values:
        return []
    max_val = max(values)
    if max_val <= 0:
        return [" " * (len(values) * width) for _ in range(height)]
    blocks = "▁▂▃▄▅▆▇█"
    lines = []
    for row in range(height - 1, -1, -1):
        chars = []
        for v in values:
            h = v / max_val * height
            if h >= row + 1:
                ch = "█"
            elif h > row:
                frac = h - row
                idx = min(int(frac * 8), 7)
                ch = blocks[idx]
            elif row == 0:
                ch = "▁"
            else:
                ch = " "
            chars.append(ch * width)
        lines.append("".join(chars))
    return lines


def print_hourly(data: dict, file: Any = None) -> None:
    """Print past-24h hourly cost as a vertical bar chart."""
    from datetime import datetime, timedelta, timezone
    from functools import partial

    p = partial(print, file=file)

    now_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    costs = []
    for i in range(23, -1, -1):
        t = now_utc - timedelta(hours=i)
        bucket = data.get(t.strftime("%Y-%m-%d"), {}).get(t.strftime("%H"), {})
        costs.append(sum(_cost_for_model(m, s) for m, s in bucket.items()))

    total = sum(costs)
    if total <= 0:
        return

    bar_w = 2
    now_local = now_utc.astimezone()
    label_chars = [" "] * (24 * bar_w)
    for col in (0, 6, 12, 18):
        t_local = now_local - timedelta(hours=23 - col)
        hh = t_local.strftime("%H")
        pos = col * bar_w
        label_chars[pos] = hh[0]
        label_chars[pos + 1] = hh[1]
    label_line = "".join(label_chars)

    bw = BOX_INNER + 2
    title = f"─ Past 24h (${total:.2f} total, local time) "
    p(f"  ╭{title:─<{bw}}╮")
    for line in _render_vertical_bars(costs, height=6, width=bar_w):
        p(f"  │  {line.center(BOX_INNER):<{BOX_INNER}s}│")
    p(f"  │  {label_line.center(BOX_INNER):<{BOX_INNER}s}│")
    p(f"  ╰{'─' * bw}╯")


def print_usage(days: int = 10, show_extra: bool = False, file: Any = None) -> None:
    """Print daily token usage stats."""
    from functools import partial

    p = partial(print, file=file)

    print_quota(show_extra=show_extra, file=file)
    p()

    data = _load_usage()
    if not data:
        p("No token usage data found.")
        return

    dates = sorted(data.keys())[-days:]

    # Pre-compute per-day stats
    rows = []
    for date in dates:
        inp, cached, output, msgs, cost = _day_stats(data[date])
        rows.append((date, msgs, inp, cached, output, cost))

    max_cost = max(r[5] for r in rows) if rows else 1

    from tabulate import tabulate

    table_rows = []
    grand_msgs = grand_input = grand_cached = grand_output = 0
    grand_cost = 0.0

    for date, msgs, inp, cached, output, cost in rows:
        grand_msgs += msgs
        grand_input += inp
        grand_cached += cached
        grand_output += output
        grand_cost += cost
        bar = _bar(cost, max_cost)
        table_rows.append(
            [date, msgs, _fmt(inp), _fmt(cached), _fmt(output), f"${cost:.2f}", bar]
        )

    table_rows.append([""] * 7)  # separator
    table_rows.append(
        [
            "TOTAL",
            grand_msgs,
            _fmt(grand_input),
            _fmt(grand_cached),
            _fmt(grand_output),
            f"${grand_cost:.2f}",
            "",
        ]
    )

    headers = ["Date", "Msgs", "Input", "Cached", "Output", "Cost", ""]
    table = tabulate(
        table_rows,
        headers=headers,
        colalign=(
            "left",
            "right",
            "right",
            "right",
            "right",
            "right",
            "left",
        ),
    )
    for line in table.splitlines():
        p(f"  {line}")

    p()
    print_hourly(data, file=file)
