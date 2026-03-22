"""Batch-generate titles and summaries for sessions using local Claude Code CLI."""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from typing import TYPE_CHECKING, Callable

from ccui.constants import CLAUDE_DIR
from ccui.data import SessionInfo, load_session_messages

if TYPE_CHECKING:
    from ccui.store import AppStore

logger = logging.getLogger(__name__)

SUMMARIES_FILE = CLAUDE_DIR / "ccui-summaries.json"
SAMPLE_SIZE = 6

PROMPT_TEMPLATE = """\
Based on this Claude Code conversation (first {n_head} and last {n_tail} messages shown), generate:
1. A short title (2-5 words, English, lowercase with hyphens, e.g. 'fix-auth-bug', 'add-metrics')
2. A one-line summary (max 80 chars, mixed Chinese-English if the conversation is in Chinese). \
If the conversation shifts topics between the beginning and end, explicitly note the transition \
(e.g. "从 X 问题转到 Y 实现" or "started with X, pivoted to Y").

Respond in EXACTLY this JSON format, nothing else:
{{"title": "...", "summary": "..."}}

Conversation:
{context}"""


def _extract_context(session: SessionInfo) -> str:
    """Extract first N and last N messages from a session for summarization."""
    all_msgs = load_session_messages(session.jsonl_path)
    if not all_msgs:
        return ""

    head = all_msgs[:SAMPLE_SIZE]
    tail = all_msgs[-SAMPLE_SIZE:]

    # Deduplicate if session is short enough that head and tail overlap
    if len(all_msgs) <= SAMPLE_SIZE * 2:
        selected = all_msgs
    else:
        selected = head + [None] + tail  # None as separator marker

    parts: list[str] = []
    for msg in selected:
        if msg is None:
            parts.append(
                f"... ({len(all_msgs) - SAMPLE_SIZE * 2} messages omitted) ..."
            )
            continue
        role = "User" if msg["role"] == "user" else "Assistant"
        text = msg["text"][:500]
        parts.append(f"{role}: {text}")
    return "\n---\n".join(parts)


def _call_claude(prompt: str) -> str:
    """Call local Claude Code CLI in print mode and return the response text."""
    result = subprocess.run(
        ["claude", "-p", "--model", "haiku", "--no-session-persistence", prompt],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited with {result.returncode}: {result.stderr}")
    return result.stdout.strip()


def _needs_summary(session: SessionInfo, store: AppStore) -> bool:
    """Check if a session needs title/summary generation."""
    return not bool(store.summaries.get(session.session_id))


def _save_summaries(summaries: dict[str, str]) -> None:
    """Write summaries dict to disk."""
    SUMMARIES_FILE.write_text(
        json.dumps(summaries, indent=2, ensure_ascii=False) + "\n"
    )


def _append_custom_title(session: SessionInfo, title: str) -> None:
    """Append a customTitle entry to the session's JSONL file."""
    entry = json.dumps({"customTitle": title}, ensure_ascii=False)
    with open(session.jsonl_path, "a") as f:
        f.write(entry + "\n")


def sessions_needing_summary(store: AppStore) -> list[SessionInfo]:
    """Return sessions that lack a title or summary."""
    return [s for s in store.sessions if _needs_summary(s, store)]


def generate_batch(
    store: AppStore,
    on_progress: Callable[[int, int, str], None] | None = None,
    on_done: Callable[[int], None] | None = None,
    cancel: threading.Event | None = None,
) -> int:
    """Synchronously generate titles/summaries for all sessions that need them.

    Calls `claude -p --model haiku` for each session — no API key needed,
    uses the local Claude Code installation.  Summaries are persisted to
    disk after each successful generation so nothing is lost on exit.

    Args:
        store: AppStore with loaded sessions.
        on_progress: Called with (current, total, title) after each session.
        on_done: Called with total generated count when finished.
        cancel: If set, abort the batch early.

    Returns:
        Number of sessions summarized.
    """
    pending = sessions_needing_summary(store)

    if not pending:
        if on_done:
            on_done(0)
        return 0

    count = 0
    for i, session in enumerate(pending):
        if cancel and cancel.is_set():
            break

        context = _extract_context(session)
        if not context:
            if on_progress:
                on_progress(i + 1, len(pending), "(skipped)")
            continue

        all_msgs = load_session_messages(session.jsonl_path)
        n_total = len(all_msgs)
        n_head = min(SAMPLE_SIZE, n_total)
        n_tail = min(SAMPLE_SIZE, max(0, n_total - SAMPLE_SIZE))
        prompt = PROMPT_TEMPLATE.format(context=context, n_head=n_head, n_tail=n_tail)

        try:
            raw = _call_claude(prompt)
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            result = json.loads(raw)
            title = result.get("title", "").strip()
            summary = result.get("summary", "").strip()
        except Exception:
            logger.warning("Failed to summarize session %s", session.session_id[:8])
            if on_progress:
                on_progress(i + 1, len(pending), "(error)")
            continue

        if title and not session.custom_title:
            _append_custom_title(session, title)
            session.custom_title = title

        if summary:
            store.summaries[session.session_id] = summary
            _save_summaries(store.summaries)

        count += 1
        if on_progress:
            on_progress(i + 1, len(pending), title)

    if on_done:
        on_done(count)

    return count
