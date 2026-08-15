# -*- coding: utf-8 -*-
"""
Skill base classes — the single, clear interface every JARVIS skill implements.

A skill is an isolated unit of capability. It declares:

    * metadata      — name, display name, description, version
    * tools         — the Gemini function-call tools it exposes (name, schema, handler)
    * permissions   — what it needs access to (see skills.permissions)
    * dependencies  — pip packages it requires
    * config        — its default configuration
    * self_test     — a smoke test run before the skill is enabled

Both built-in wrappers and dynamically-created custom skills subclass ``Skill``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class SkillError(Exception):
    """Raised when a skill fails to load, run, or self-test."""


@dataclass
class SkillContext:
    """Runtime environment handed to every skill execution.

    The manager builds one of these and rebinds it into each loaded skill.
    It deliberately has no knowledge of skills internals — it is a narrow,
    read-only surface for the runtime (UI, speech, API key, base directory).
    """

    ui: Any = None                                   # JarvisUI: write_log / show_content / set_state / current_file …
    speak: Callable[[str], None] = field(default=lambda text: None)
    api_key: Callable[[], str] = field(default=lambda: "")
    base_dir: Any = None                             # pathlib.Path — project root

    def log(self, message: str) -> None:
        try:
            if self.ui is not None:
                self.ui.write_log(message)
            else:
                print(message)
        except Exception:
            print(message)


@dataclass
class Tool:
    """One Gemini function-call tool exposed by a skill."""

    name: str
    description: str
    parameters: dict
    handler: Optional[Callable[[dict, "SkillContext"], str]] = None

    def declaration(self) -> dict:
        """Return the Gemini function_declaration dict for this tool."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass
class SkillTestResult:
    """Outcome of a skill self-test / validation."""

    ok: bool
    message: str = ""
    checks: dict = field(default_factory=dict)


class Skill:
    """Base class for all skills.

    Subclasses may either:

        * set ``self.tools = [Tool(...)]`` with per-tool ``handler`` functions
          (built-in wrappers do this), or
        * override ``handle(tool_name, args, context)`` and leave ``tools``
          handlers empty (custom generated skills do this — a single dispatch
          method is friendlier to an LLM writing the code).
    """

    # ── metadata ────────────────────────────────────────────────────────────
    name: str = ""
    display_name: str = ""
    description: str = ""
    version: str = "1.0.0"

    # ── declared requirements ───────────────────────────────────────────────
    permissions: list[str] = []        # subset of KNOWN_PERMISSIONS
    dependencies: list[str] = []       # pip package names
    config: dict = {}                  # default configuration values
    config_schema: dict = {}           # optional lightweight schema for config

    # ── tools ───────────────────────────────────────────────────────────────
    tools: list[Tool] = []

    def __init__(self, context: Optional[SkillContext] = None):
        self.context = context or SkillContext()

    # ── lifecycle ───────────────────────────────────────────────────────────
    def bind(self, context: SkillContext) -> None:
        self.context = context

    def on_load(self) -> None:
        """Called once after the skill module is imported and instantiated."""

    def on_unload(self) -> None:
        """Called once before the skill is dropped from the registry."""

    # ── tool lookup ─────────────────────────────────────────────────────────
    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools]

    def get_tool(self, tool_name: str) -> Optional[Tool]:
        for t in self.tools:
            if t.name == tool_name:
                return t
        return None

    # ── dispatch ────────────────────────────────────────────────────────────
    def run(self, tool_name: str, args: dict, context: Optional[SkillContext] = None) -> str:
        """Execute ``tool_name`` with ``args``. Returns a plain result string."""
        if context is not None:
            self.context = context
        tool = self.get_tool(tool_name)
        if tool is not None:
            if tool.handler is not None:
                return tool.handler(args or {}, self.context) or "Done."
            return self.handle(tool_name, args or {}, self.context) or "Done."
        # No explicit tool declaration — fall back to handle() so custom skills
        # may dispatch arbitrary names.
        return self.handle(tool_name, args or {}, self.context) or "Done."

    def handle(self, tool_name: str, args: dict, context: SkillContext) -> str:
        """Override in custom skills that don't attach per-tool handlers."""
        raise SkillError(
            f"Skill '{self.name}' does not implement tool '{tool_name}'"
        )

    # ── self-test ───────────────────────────────────────────────────────────
    def self_test(self, context: Optional[SkillContext] = None) -> SkillTestResult:
        """Smoke test. Override in custom skills; default passes trivially."""
        return SkillTestResult(ok=True, message="no self_test defined (default pass)")
