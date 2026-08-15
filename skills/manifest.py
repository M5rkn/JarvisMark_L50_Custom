# -*- coding: utf-8 -*-
"""
Skill manifest — the on-disk descriptor for a custom skill.

A custom skill lives in ``skills/custom/<name>/`` and consists of:

    manifest.json   — this descriptor (metadata, permissions, deps, config, tools)
    skill.py        — a module defining ``class Skill(SkillBase)``

The manifest is the *static* contract; the registry reads it without importing
any code, so even a broken skill can be listed, disabled, or removed safely.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class ToolSpec:
    """Static description of a tool (schema only — the handler lives in code)."""

    name: str
    description: str
    parameters: dict = field(default_factory=dict)

    def as_tool(self, handler=None) -> Any:
        from skills.base import Tool
        return Tool(
            name=self.name,
            description=self.description,
            parameters=self.parameters or {"type": "OBJECT", "properties": {}},
            handler=handler,
        )


@dataclass
class SkillManifest:
    name: str
    display_name: str = ""
    description: str = ""
    version: str = "1.0.0"
    entrypoint: str = "skill.py"
    class_name: str = "Skill"
    permissions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    config: dict = field(default_factory=dict)
    config_schema: dict = field(default_factory=dict)
    tools: list[ToolSpec] = field(default_factory=list)

    # ── serialisation ───────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def dump(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "SkillManifest":
        data = json.loads(path.read_text(encoding="utf-8"))
        tools = [ToolSpec(**t) for t in data.get("tools", [])]
        return cls(
            name=data.get("name", ""),
            display_name=data.get("display_name", ""),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            entrypoint=data.get("entrypoint", "skill.py"),
            class_name=data.get("class_name", "Skill"),
            permissions=data.get("permissions", []),
            dependencies=data.get("dependencies", []),
            config=data.get("config", {}),
            config_schema=data.get("config_schema", {}),
            tools=tools,
        )

    # ── validation ──────────────────────────────────────────────────────────
    def validate(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not self.name or not self.name.replace("_", "").replace("-", "").isalnum():
            errors.append("manifest.name must be a non-empty alphanumeric (dash/underscore ok) identifier")
        if not self.description:
            errors.append("manifest.description is required")
        from skills.permissions import validate_permissions
        ok, unknown = validate_permissions(self.permissions)
        if not ok:
            errors.append(f"unknown permissions: {unknown}")
        if not self.tools:
            errors.append("manifest.tools must declare at least one tool")
        for t in self.tools:
            if not t.name:
                errors.append("a tool is missing its name")
            if not t.description:
                errors.append(f"tool '{t.name}' is missing a description")
        return (not errors), errors
