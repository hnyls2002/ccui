"""Batch-generate titles and summaries for sessions and notes using local Claude Code CLI."""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from typing import TYPE_CHECKING, Callable

from ccui.constants import CLAUDE_DIR
from ccui.data import SessionInfo, load_session_messages
from ccui.notes import NoteInfo

if TYPE_CHECKING:
    from ccui.store import AppStore

logger = logging.getLogger(__name__)

SUMMARIES_FILE = CLAUDE_DIR / "ccui-summaries.json"
NOTE_SUMMARIES_FILE = CLAUDE_DIR / "ccui-note-summaries.json"
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


def _call_claude(prompt: str, cancel: threading.Event | None = None) -> str:
    """Call local Claude Code CLI in print mode and return the response text.

    If *cancel* is set while the subprocess is running, kill it immediately.
    """
    proc = subprocess.Popen(
        ["claude", "-p", "--model", "haiku", "--no-session-persistence", prompt],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Poll so we can react to cancel quickly
    while proc.poll() is None:
        if cancel and cancel.is_set():
            proc.kill()
            raise RuntimeError("cancelled")
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude exited with {proc.returncode}: {proc.stderr.read()}"
        )
    return (proc.stdout.read() or "").strip()


def _needs_summary(session: SessionInfo, store: AppStore) -> bool:
    """Check if a session needs title/summary generation.

    A session is only considered summarized when it has BOTH a title and a summary.
    """
    has_summary = bool(store.summaries.get(session.session_id))
    has_title = bool(session.custom_title)
    return not (has_summary and has_title)


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
            raw = _call_claude(prompt, cancel=cancel)
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

        # Both title and summary must be present; skip if either is missing
        # so the session will be retried next time.
        if not title or not summary:
            logger.warning(
                "Incomplete response for %s (title=%r, summary=%r), will retry",
                session.session_id[:8],
                bool(title),
                bool(summary),
            )
            if on_progress:
                on_progress(i + 1, len(pending), "(incomplete)")
            continue

        if not session.custom_title:
            _append_custom_title(session, title)
            session.custom_title = title

        store.summaries[session.session_id] = summary
        _save_summaries(store.summaries)

        count += 1
        if on_progress:
            on_progress(i + 1, len(pending), title)

    if on_done:
        on_done(count)

    return count


# ═══════════════════════════════════════════════════════════════════════
# Note / Plan summaries
# ═══════════════════════════════════════════════════════════════════════

NOTE_PROMPT_TEMPLATE = """\
Based on this {kind} file content, generate a one-line summary (max 80 chars, \
mixed Chinese-English if the content is in Chinese).

Respond in EXACTLY this JSON format, nothing else:
{{"summary": "..."}}

Content:
{content}"""


def _read_note_content(note: NoteInfo) -> str:
    """Read note content, stripping frontmatter."""
    try:
        text = note.path.read_text()
    except OSError:
        return ""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        closed = False
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                lines = lines[i + 1 :]
                closed = True
                break
        if not closed:
            # Unclosed frontmatter — skip the opening --- line at minimum
            lines = lines[1:]
    content = "\n".join(lines).strip()
    # Truncate to ~2000 chars for the prompt
    return content[:2000]


def _save_note_summaries(summaries: dict[str, str]) -> None:
    NOTE_SUMMARIES_FILE.write_text(
        json.dumps(summaries, indent=2, ensure_ascii=False) + "\n"
    )


def notes_needing_summary(notes: list[NoteInfo], store: AppStore) -> list[NoteInfo]:
    return [n for n in notes if not store.note_summaries.get(str(n.path))]


def generate_note_batch(
    notes: list[NoteInfo],
    store: AppStore,
    on_progress: Callable[[int, int, str], None] | None = None,
    on_done: Callable[[int], None] | None = None,
    cancel: threading.Event | None = None,
) -> int:
    """Generate summaries for notes/plans that lack them."""
    pending = notes_needing_summary(notes, store)

    if not pending:
        if on_done:
            on_done(0)
        return 0

    count = 0
    for i, note in enumerate(pending):
        if cancel and cancel.is_set():
            break

        content = _read_note_content(note)
        if not content:
            if on_progress:
                on_progress(i + 1, len(pending), "(skipped)")
            continue

        prompt = NOTE_PROMPT_TEMPLATE.format(kind=note.kind, content=content)

        try:
            raw = _call_claude(prompt, cancel=cancel)
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            result = json.loads(raw)
            summary = result.get("summary", "").strip()
        except Exception:
            logger.warning("Failed to summarize %s %s", note.kind, note.path.name)
            if on_progress:
                on_progress(i + 1, len(pending), "(error)")
            continue

        if summary:
            store.note_summaries[str(note.path)] = summary
            _save_note_summaries(store.note_summaries)

        count += 1
        if on_progress:
            on_progress(i + 1, len(pending), note.title)

    if on_done:
        on_done(count)

    return count
