# -*- coding: utf-8 -*-
"""
Context Engine — short-term working memory and reference resolution for JARVIS.

Tracks, in a thread-safe way, the small amount of *working* state the assistant
needs to resolve elided references like "open it", "run that", "do it again",
"continue", "now fix this", or "what about the previous one?":

  * current_task    — the task the user is currently working on
  * current_app     — the last app the user opened / is interacting with
  * current focus   — the explicit object/entity the user is pointing at ("it")
  * active topic    — the subject the user is currently discussing
  * last_action     — the most recent user-visible action and its outcome
  * recent_commands — the last few executed tools (for "do it again")

This does NOT replace the Gemini Live conversation (Gemini already keeps
turn-to-turn history server-side). It exists so a reconnect or restart does not
lose the immediate thread, and so the prompt can carry a compact, structured
"ACTIVE CONTEXT" block that makes pronoun/elided references unambiguous.

It also exposes :func:`remember` — a single entry point that classifies a
free-form fact into the right memory layer + importance and writes it via the
existing layered memory store, so there is exactly ONE place that decides "what
to keep". Layer detection is delegated to the existing ``guess_memory_layer``
heuristic (single source of truth); only the importance weighting is added here.

Import-safe: stdlib only at import time (no PyQt / sounddevice / Gemini here).
"""

from __future__ import annotations

import threading
from collections import deque

# ── Tunables ───────────────────────────────────────────────────────────────────
_RECENT_COMMANDS_MAX = 8        # how many executed tools to remember
_CONTEXT_MAX_CHARS   = 900      # cap on the ACTIVE CONTEXT prompt block

# Importance classes (requirement #9) → (layer, importance) intent:
#   TEMPORARY  → short_term, low importance
#   IMPORTANT  → long_term, high importance
#   PERSISTENT → long_term, high importance (durable identity / preference)
#   PROJECT    → project,   medium-high importance
#   EPISODIC   → episodic,  medium importance

_PERSISTENT_HINTS = (
    "always", "never", "favorite", "prefer", "love", "hate", "name is",
    "birthday", "language", "my real name", "i am", "i'm",
)
_PROJECT_HINTS = (
    "project", "code", "bug", "error", "fix", "config", "install",
    "dependency", "api", "function", "build", "deploy", "git", "python",
    "database", "module", "framework", "library", "ide",
)


def classify_content(content: str) -> tuple[str, float]:
    """
    Classify a free-form fact into ``(layer, importance)``.

    Layer is delegated to the existing ``guess_memory_layer`` heuristic (the
    single source of truth for layer detection); only the importance weighting
    is computed here, so the two never disagree about which layer a fact lands in.
    """
    content = (content or "").strip()
    if not content:
        return "long_term", 0.5

    try:
        from memory.memory_manager import guess_memory_layer
        layer = guess_memory_layer(content)
    except Exception:
        layer = "long_term"

    low = content.lower()

    # Durable personal facts are IMPORTANT/PERSISTENT and belong in long_term
    # regardless of what the layer heuristic guessed (a preference phrased with
    # "currently" should still be durable).
    if any(h in low for h in _PERSISTENT_HINTS):
        return "long_term", 0.85

    if layer == "project":
        return "project", 0.7
    if layer == "short_term":
        return "short_term", 0.35
    if layer == "episodic":
        return "episodic", 0.5
    return "long_term", 0.5


def remember(content: str, default_layer: str | None = None,
             labels: list[str] | None = None, embed_async: bool = True) -> dict:
    """
    Classify ``content`` and write it to the layered memory store.

    Used by the context engine (compaction) and as the single code-side entry
    point for "what to keep"; the model keeps its own ``add_memory`` tool.
    """
    content = (content or "").strip()
    if not content:
        return {}

    layer, importance = classify_content(content)
    if default_layer in ("short_term", "long_term", "project", "episodic"):
        layer = default_layer

    try:
        from memory.layered_memory import add_memory
        return add_memory(
            content=content, layer=layer, labels=labels, importance=importance,
            source="context_engine", embed_async=embed_async,
        )
    except Exception as e:
        print(f"[Context] ⚠️ remember failed: {e}")
        return {}


def _remember_keyed(key: str, value: str) -> None:
    """Store a singleton 'key: value' context fact in short_term (no embedding).

    The stable label lets the layered store's same-fact upsert replace the old
    value instead of accumulating a new entry each time the key changes.
    """
    try:
        from memory.layered_memory import add_memory
        add_memory(
            content=f"{key}: {value}",
            layer="short_term",
            labels=["context", key.replace(" ", "_")],
            importance=0.4,
            source="context_engine",
            embed_async=False,
        )
    except Exception as e:
        print(f"[Context] ⚠️ persist '{key}' failed: {e}")


def _persist_async(fn) -> None:
    """Run a persistence call on a daemon thread so the caller never blocks."""
    try:
        threading.Thread(target=fn, daemon=True).start()
    except Exception:
        pass


class ContextEngine:
    """Thread-safe holder of short-term working state for reference resolution."""

    def __init__(self):
        self._lock = threading.RLock()
        self.current_task: str | None = None
        self.current_app: str | None = None
        self.reference: str | None = None       # explicit focus / "it"
        self.active_topic: str | None = None    # subject currently being discussed
        self.last_action: tuple | None = None   # (tool, ok)
        self._recent: deque = deque(maxlen=_RECENT_COMMANDS_MAX)

    # ── mutations ────────────────────────────────────────────────────────────

    def set_task(self, task: str | None) -> None:
        task = (task or "").strip() or None
        with self._lock:
            self.current_task = task
        if task:
            _persist_async(lambda: _remember_keyed("current task", task))

    def clear_task(self) -> None:
        self.set_task(None)

    def set_app(self, app: str | None) -> None:
        app = (app or "").strip() or None
        with self._lock:
            self.current_app = app
        if app:
            _persist_async(lambda: _remember_keyed("current app", app))

    def set_reference(self, ref: str | None) -> None:
        self.reference = (ref or "").strip() or None

    def set_topic(self, topic: str | None) -> None:
        topic = (topic or "").strip() or None
        with self._lock:
            self.active_topic = topic
        if topic:
            _persist_async(lambda: _remember_keyed("current topic", topic))

    def clear_topic(self) -> None:
        self.set_topic(None)

    def remember(self, content: str, default_layer: str | None = None,
                 labels: list[str] | None = None, embed_async: bool = True) -> dict:
        """Classify + store a fact (delegates to the module-level :func:`remember`)."""
        return remember(content, default_layer=default_layer, labels=labels, embed_async=embed_async)

    def complete_command(self, tool: str, args: dict | None, result: str, ok: bool = True) -> str:
        """Record structured execution metadata. Returns ``result`` unchanged.

        Tool results may include untrusted web or file content, so their bodies
        must never be copied into the system-prompt context.
        """
        args = dict(args or {})
        with self._lock:
            self.last_action = (tool, bool(ok))
            self._recent.append((tool, args, bool(ok)))
            if ok:
                self._infer_app(tool, args)
        return result

    def _infer_app(self, tool: str, args: dict) -> None:
        if tool == "open_app" and args.get("app_name"):
            self.set_app(str(args["app_name"]))
        elif tool == "game_updater" and args.get("action") in ("launch", "install"):
            game = str(args.get("game_name") or "").strip()
            if game:
                self.set_app(game)
        elif tool in ("browser_control", "file_processor", "file_controller"):
            self.set_app("browser" if tool == "browser_control" else "files")
        elif tool in ("work_mode", "game_mode"):
            self.set_app(tool.replace("_", " "))
        elif tool == "computer_settings" and args.get("action") == "close_app":
            closed = str(args.get("app_name") or args.get("value") or "").strip().lower()
            if closed and self.current_app and closed in self.current_app.lower():
                self.set_app(None)

    # ── prompt context ───────────────────────────────────────────────────────

    def build_context_block(self) -> str:
        """A compact, prompt-safe ACTIVE CONTEXT block (empty when nothing is known)."""
        with self._lock:
            lines: list[str] = []
            if self.current_task:
                lines.append(f"Current task: {self.current_task}")
            if self.current_app:
                lines.append(f"Current application: {self.current_app}")
            if self.reference:
                lines.append(f"Current focus/subject: {self.reference}")
            if self.active_topic:
                lines.append(f"Active topic: {self.active_topic}")
            if self.last_action:
                tool, ok = self.last_action
                status = "succeeded" if ok else "failed"
                lines.append(f"Last action: {tool} — {status}")
            if self._recent:
                cmds = [t for t, _, ok in list(self._recent)[-6:] if ok]
                if cmds:
                    lines.append(f"Recent commands: {', '.join(cmds)}")

        if not lines:
            return ""

        block = (
            "[ACTIVE CONTEXT — use to resolve 'it'/'this'/'that'/'previous'/'again'/"
            "'continue' without asking; never recite this block]\n"
            + "\n".join(f"  - {l}" for l in lines)
        )
        if len(block) > _CONTEXT_MAX_CHARS:
            block = block[: _CONTEXT_MAX_CHARS - 1].rstrip() + "…"
        return block + "\n"
