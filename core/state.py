# -*- coding: utf-8 -*-
"""
Task state machine + decision/orchestration layer for JARVIS.

A lightweight, import-safe (stdlib-only) holder that models the lifecycle of a
single user request through the pipeline:

    USER REQUEST → INTENT → CONTEXT → SKILL → ACTION → VERIFICATION → RESPONSE

Task states:

    IDLE → UNDERSTANDING → PLANNING → EXECUTING → VERIFYING → COMPLETED
                                         ↘                        ↘
                                        FAILED          WAITING_FOR_CONFIRMATION

Gemini's function-calling stays the router (it picks the tool). This layer adds
observability and honest success/failure handling on top of that routing, plus a
minimal failure classifier so a failed action can be retried or re-routed safely
instead of being blindly repeated.

Import-safe: stdlib only at import time.
"""

from __future__ import annotations

import threading
import uuid

# ── Task states ────────────────────────────────────────────────────────────────
IDLE = "IDLE"
UNDERSTANDING = "UNDERSTANDING"
PLANNING = "PLANNING"
EXECUTING = "EXECUTING"
VERIFYING = "VERIFYING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"

TASK_STATES = (
    IDLE, UNDERSTANDING, PLANNING, EXECUTING,
    VERIFYING, COMPLETED, FAILED, WAITING_FOR_CONFIRMATION,
)

# ── Failure classification ─────────────────────────────────────────────────────
_FATAL_HINTS = (
    "api key not valid", "1007", "permission denied", "access denied",
    "cancelled", "canceled", "unknown tool", "not implemented",
)
_RETRYABLE_HINTS = (
    "timed out", "timeout", "timedout", "connection", "unreachable",
    "getaddrinfo", "connectionrefused", "connection refused", "temporarily",
    "busy", "rate limit", "429", "503", "network", "offline", "dns",
    "retry",
)


def classify_failure(error: str) -> str:
    """Classify an error string as 'fatal' | 'retryable' | 'alternative'."""
    e = (error or "").lower()
    if any(k in e for k in _FATAL_HINTS):
        return "fatal"
    if any(k in e for k in _RETRYABLE_HINTS):
        return "retryable"
    return "alternative"


# High-precision failure markers — deliberately narrow so a legitimate result
# (e.g. a search answer that happens to mention "error") is never misread.
_ERROR_MARKERS = (
    " failed", "exception", "traceback", "could not ", "unable to ",
)


def verify_success(result: str | None) -> bool:
    """Return True unless ``result`` clearly indicates a tool failure.

    This is the verification gate: it never infers success from an empty/absent
    result — the caller's explicit ``ok`` flag governs that — it only *demotes*
    a result that reads like an error string.
    """
    r = (result or "").lower()
    if not r:
        return True
    return not any(m in r for m in _ERROR_MARKERS)


class TaskState:
    """Thread-safe holder for the state of the current task."""

    def __init__(self):
        self._lock = threading.RLock()
        self.state = IDLE
        self.intent = ""
        self.task_id = None
        self.started = None
        self.updated = None

    def set_intent(self, intent: str) -> None:
        with self._lock:
            self.intent = (intent or "").strip()

    def transition(self, new_state: str) -> None:
        if new_state not in TASK_STATES:
            raise ValueError(f"Unknown task state: {new_state!r}")
        with self._lock:
            self.state = new_state
            import time
            self.updated = time.time()

    def is_terminal(self) -> bool:
        with self._lock:
            return self.state in (COMPLETED, FAILED)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self.state,
                "intent": self.intent,
                "task_id": self.task_id,
                "updated": self.updated,
            }


class DecisionLayer:
    """
    A thin orchestration layer around a single tool execution.

    ``start`` records the intent and enters EXECUTING; ``finish`` verifies the
    outcome and lands on COMPLETED or FAILED. On failure it returns a short
    recovery hint for the model, so the assistant can retry or re-route rather
    than hallucinate success.
    """

    def __init__(self, state: TaskState | None = None):
        self.state = state or TaskState()

    def start(self, tool: str, args: dict | None = None) -> str:
        """Record the intent and advance IDLE → UNDERSTANDING → EXECUTING."""
        self.state.task_id = uuid.uuid4().hex[:8]
        self.state.set_intent(tool)
        self.state.transition(UNDERSTANDING)
        self.state.transition(EXECUTING)
        return self.state.task_id

    def wait_for_confirmation(self) -> None:
        """Mark that the task is paused pending an explicit user confirmation."""
        self.state.transition(WAITING_FOR_CONFIRMATION)

    def finish(self, ok: bool, result: str | None = None, error: str | None = None) -> str | None:
        """
        Verify and close the current execution.

        Returns a recovery hint string on failure (for the model), or None on
        success. The result is treated as verified-success only when ``ok`` is
        explicitly True — this layer never infers success from an empty result.
        """
        self.state.transition(VERIFYING)
        if ok:
            self.state.transition(COMPLETED)
            return None
        self.state.transition(FAILED)
        return self.recovery_hint(self.state.intent, error or result or "")

    def recovery_hint(self, tool: str, error: str, classification: str | None = None) -> str:
        cls = classification or classify_failure(error)
        short = (error or "").strip()
        if len(short) > 120:
            short = short[:119].rstrip() + "…"
        if cls == "retryable":
            return (
                f"[RECOVERY] '{tool}' hit a temporary error ({short}). "
                "One retry may succeed; otherwise report it."
            )
        if cls == "fatal":
            return (
                f"[RECOVERY] '{tool}' hit a non-recoverable error ({short}). "
                "Report the actual problem to the user."
            )
        return (
            f"[RECOVERY] '{tool}' failed ({short}). "
            "Try a different approach or tool if safe, then report what happened."
        )
