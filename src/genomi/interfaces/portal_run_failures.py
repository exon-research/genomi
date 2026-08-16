"""Patient-facing wording for a run that ended without an answer.

A host-agent run can stop for reasons the person in the conversation has to act
on: the assistant runtime hit its account limit, the runtime is not installed,
the local process died. The raw terminal error is provider machinery — JSON
payloads, provider error codes, exception text — and belongs in the collapsed
work trail. This module turns that raw string into the sentence the
conversation shows, so both the live run stream and the stored conversation
say the same actionable thing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from . import portal_turns

FAILED_RUN_STATUSES = frozenset({"failed", "error"})
CANCELED_RUN_STATUSES = frozenset({"canceled", "cancelled"})

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_MACHINERY_RE = re.compile(r"[{}]|\b\w+Error\b|\bTraceback\b|\bexit code\b", re.IGNORECASE)

_USAGE_LIMIT_MARKERS = (
    "usage limit",
    "usagelimit",
    "quota",
    "rate limit",
    "rate_limit",
    "too many requests",
    "out of credits",
    "purchase more credits",
    "insufficient_quota",
)
_UNAVAILABLE_MARKERS = (
    "unsupported or unavailable agent",
    "no such file or directory",
    "command not found",
    "executable not found",
    "is not installed",
    "could not be started",
    "could not be attached",
)
_TIMEOUT_MARKERS = ("timed out", "timeout")
_RESTART_MARKERS = ("interrupted by a server restart", "stale_after_restart")


@dataclass(frozen=True)
class RunFailure:
    """One terminal run outcome, phrased for the person reading the chat."""

    reason: str
    headline: str
    next_steps: tuple[str, ...]
    detail: str = ""

    def message_text(self) -> str:
        lines = [self.headline]
        if self.detail:
            lines.extend(("", self.detail))
        if self.next_steps:
            lines.append("")
            lines.append("What you can do:")
            lines.extend(f"- {step}" for step in self.next_steps)
        return "\n".join(lines)


_SWITCH_ASSISTANT_STEP = (
    "Pick a different assistant under Workspace details → Local assistant → Assistant troubleshooting, "
    "then send the question again."
)
_RESEND_STEP = "Send the question again once the assistant is available; your records stay in this workspace."


def classify_run_failure(error: str, *, status: str = "failed") -> RunFailure:
    raw = str(error or "")
    detail = _human_detail(raw)
    haystack = raw.lower()
    if str(status or "").strip().lower() in CANCELED_RUN_STATUSES:
        return RunFailure(
            reason="run_stopped_by_you",
            headline="This turn was stopped before the assistant finished.",
            next_steps=("Send the question again when you want Genomi to continue.",),
        )
    if _contains(haystack, _USAGE_LIMIT_MARKERS):
        return RunFailure(
            reason="assistant_usage_limit_reached",
            headline="Your assistant ran out of usage allowance, so this turn stopped before any research was done.",
            next_steps=(
                "Wait until your assistant's allowance resets, then ask again.",
                _SWITCH_ASSISTANT_STEP,
                "Your question and attached records stay in this conversation, so nothing needs to be re-entered.",
            ),
            detail=detail,
        )
    if _contains(haystack, _RESTART_MARKERS):
        return RunFailure(
            reason="assistant_stopped_at_restart",
            headline="Genomi restarted while this turn was running, so the assistant never finished it.",
            next_steps=("Send the question again to restart the research.",),
        )
    if _contains(haystack, _UNAVAILABLE_MARKERS):
        return RunFailure(
            reason="assistant_unavailable",
            headline="Genomi could not start a local assistant for this turn.",
            next_steps=(
                "Check Workspace details → Local assistant → Assistant troubleshooting to see which assistants Genomi can run.",
                _RESEND_STEP,
            ),
            detail=detail,
        )
    if _contains(haystack, _TIMEOUT_MARKERS):
        return RunFailure(
            reason="assistant_timed_out",
            headline="The assistant stopped responding, so this turn ended without an answer.",
            next_steps=("Send the question again.", _SWITCH_ASSISTANT_STEP),
            detail=detail,
        )
    return RunFailure(
        reason="assistant_stopped_unexpectedly",
        headline="The assistant stopped before it could answer this question.",
        next_steps=(
            "Send the question again.",
            "Open the work trail below for the technical detail if the same thing keeps happening.",
        ),
        detail=detail,
    )


def failure_message_text(error: str, *, status: str = "failed") -> str:
    return classify_run_failure(error, status=status).message_text()


def _contains(haystack: str, markers: tuple[str, ...]) -> bool:
    return any(marker in haystack for marker in markers)


def _human_detail(raw: str) -> str:
    """Return the provider's own readable sentence, or nothing.

    Provider payloads embed a human sentence beside machine fields. Only that
    sentence is allowed through; anything still carrying braces, provider error
    codes, or exception text is dropped rather than shown to the reader.
    """

    clean = portal_turns.prompt_safe_text(_json_message(raw)).strip()
    if not clean or _MACHINERY_RE.search(clean):
        return ""
    return clean


def _json_message(raw: str) -> str:
    match = _JSON_OBJECT_RE.search(raw)
    if match is None:
        return ""
    try:
        payload = json.loads(match.group(0))
    except (TypeError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("message", "detail", "description"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
