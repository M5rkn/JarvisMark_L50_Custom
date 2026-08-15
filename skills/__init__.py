# -*- coding: utf-8 -*-
"""
JARVIS Skills/Plugins framework.

A modular, isolated, dynamically loadable skill system.

    base         — Skill / Tool / SkillContext / SkillTestResult (the interface)
    permissions  — permission vocabulary every skill declares against
    manifest     — SkillManifest (JSON metadata for custom skills)
    registry     — discovery + load/unload/enable/disable + persistent state
    manager      — orchestration: detect → load → run → create → test → register
    dependencies — safe dependency installation
    tester       — import/schema/smoke-test harness for new skills
    builder      — LLM-driven generation of new skills

The two skill flavours share one interface:

    * built-in skills  (``skills/builtin/``) — wrap the existing ``actions/*``
      functions so no current feature is lost, exposed through the same Skill API.
    * custom skills    (``skills/custom/<name>/``) — fully self-contained
      ``manifest.json`` + ``skill.py``, created at runtime by the manager.

See ``skills/manager.py`` for the lifecycle contract.
"""

from skills.base import (
    Skill,
    Tool,
    SkillContext,
    SkillTestResult,
    SkillError,
)
from skills.permissions import KNOWN_PERMISSIONS
from skills.registry import SkillRegistry
from skills.manager import SkillManager

__all__ = [
    "Skill",
    "Tool",
    "SkillContext",
    "SkillTestResult",
    "SkillError",
    "KNOWN_PERMISSIONS",
    "SkillRegistry",
    "SkillManager",
]
