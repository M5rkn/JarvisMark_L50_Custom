# -*- coding: utf-8 -*-
"""
SkillRegistry — discovery, isolation, and lifecycle of skills.

The registry is the source of truth for *which* skills exist and their state
(enabled / disabled / quarantined). It persists that state to
``skills/config/skills.json`` so disabling a broken skill survives a restart
without ever having to import its code again.

Isolation guarantees:

    * a disabled skill's code is never imported
    * a failing skill is unloaded (removed from ``sys.modules``) on disable
    * listing/inspection reads only manifests — never executes skill code
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Optional

from skills.base import Skill, SkillContext
from skills.manifest import SkillManifest


class SkillRegistry:
    STATE_FILE_NAME = "skills.json"

    def __init__(self, base_dir: Path, context: Optional[SkillContext] = None):
        self.base_dir = base_dir
        self.context = context or SkillContext()
        self.skills_dir = base_dir / "skills"
        self.builtin_dir = self.skills_dir / "builtin"
        self.custom_dir = self.skills_dir / "custom"
        self.disabled_dir = self.skills_dir / "disabled"
        self.config_dir = self.skills_dir / "config"
        self.state_path = self.config_dir / self.STATE_FILE_NAME

        self._state: dict = {"skills": {}}
        self._builtin: dict[str, Skill] = {}       # name -> Skill instance (unbound)
        self._manifests: dict[str, SkillManifest] = {}  # custom manifests by name
        self._loaded: dict[str, Skill] = {}        # name -> bound Skill instance
        self._tool_index: dict[str, str] = {}      # tool_name -> skill_name

        self._load_state()

    # ── state persistence ───────────────────────────────────────────────────
    def _load_state(self) -> None:
        try:
            if self.state_path.exists():
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                self._state = data if isinstance(data, dict) and "skills" in data else {"skills": {}}
        except Exception as e:  # noqa: BLE001
            print(f"[Skills] ⚠️ Could not read state ({e}) — starting fresh.")
            self._state = {"skills": {}}

    def save_state(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _skill_state(self, name: str) -> dict:
        return self._state["skills"].setdefault(name, {})

    # ── discovery ───────────────────────────────────────────────────────────
    def register_builtin(self, skill: Skill) -> None:
        """Register a built-in skill instance (code already importable)."""
        self._builtin[skill.name] = skill
        st = self._skill_state(skill.name)
        st.setdefault("builtin", True)
        st.setdefault("tools", skill.tool_names())
        # Built-in skills keep working exactly as before: enabled + pre-granted.
        st.setdefault("enabled", True)
        st["permissions_granted"] = list(dict.fromkeys(st.get("permissions_granted", []) + skill.permissions))
        st.setdefault("config", dict(skill.config))
        for t in skill.tool_names():
            self._tool_index[t] = skill.name

    def discover_custom(self) -> None:
        """Scan ``skills/custom/*/manifest.json`` — no code is imported here."""
        if not self.custom_dir.is_dir():
            return
        for manifest_path in sorted(self.custom_dir.glob("*/manifest.json")):
            try:
                manifest = SkillManifest.load(manifest_path)
            except Exception as e:  # noqa: BLE001
                print(f"[Skills] ⚠️ bad manifest {manifest_path.name}: {e}")
                continue
            self._manifests[manifest.name] = manifest
            st = self._skill_state(manifest.name)
            st.setdefault("builtin", False)
            st.setdefault("tools", [t.name for t in manifest.tools])
            # First discovery of a custom skill: leave it disabled (requires approval).
            st.setdefault("enabled", False)
            st.setdefault("config", dict(manifest.config))
            for t in manifest.tools:
                self._tool_index.setdefault(t.name, manifest.name)

    def load(self, name: str) -> Skill:
        """Import and bind a skill's code. Raises if already loaded or broken."""
        if name in self._loaded:
            return self._loaded[name]

        if name in self._builtin:
            skill = self._builtin[name]
        elif name in self._manifests:
            skill = self._load_custom(name)
        else:
            raise LookupError(f"unknown skill '{name}'")

        skill.bind(self.context)
        try:
            skill.on_load()
        except Exception as e:  # noqa: BLE001
            print(f"[Skills] ⚠️ on_load failed for '{name}': {e}")
        self._loaded[name] = skill
        return skill

    def _load_custom(self, name: str) -> Skill:
        manifest = self._manifests[name]
        skill_dir = self.custom_dir / name
        entrypoint = skill_dir / manifest.entrypoint
        if not entrypoint.is_file():
            raise FileNotFoundError(f"skill '{name}' entrypoint missing: {entrypoint}")

        module_name = f"skills.custom.{name}.{entrypoint.stem}"
        spec = importlib.util.spec_from_file_location(module_name, entrypoint)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {entrypoint}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        cls = getattr(module, manifest.class_name, None)
        if cls is None:
            # allow the module to expose a module-level `skill` instance instead
            cls = getattr(module, "skill", None)
        if cls is None:
            raise AttributeError(
                f"skill '{name}' module has no class '{manifest.class_name}' or 'skill' instance"
            )
        if isinstance(cls, type):
            skill = cls()
        else:
            skill = cls
        # overlay default config from manifest if the skill didn't define any
        if not skill.config:
            skill.config = dict(manifest.config)
        if not skill.tools:
            skill.tools = [t.as_tool() for t in manifest.tools]
        return skill

    def unload(self, name: str) -> None:
        """Drop a loaded skill and remove its module from sys.modules."""
        skill = self._loaded.pop(name, None)
        if skill is not None:
            try:
                skill.on_unload()
            except Exception:  # noqa: BLE001
                pass
        for mod_name in [m for m in sys.modules if m.startswith(f"skills.custom.{name}.")]:
            sys.modules.pop(mod_name, None)

    # ── lifecycle ───────────────────────────────────────────────────────────
    def enable(self, name: str, grant_permissions: Optional[list[str]] = None) -> Skill:
        skill = self.load(name)
        st = self._skill_state(name)
        st["enabled"] = True
        if grant_permissions is not None:
            st["permissions_granted"] = list(dict.fromkeys(grant_permissions))
        st["failure_count"] = 0
        self.save_state()
        return skill

    def disable(self, name: str, quarantine: bool = False) -> None:
        st = self._skill_state(name)
        st["enabled"] = False
        self.unload(name)
        if quarantine:
            st["quarantined"] = True
        self.save_state()

    def remove(self, name: str) -> None:
        """Disable + remove a custom skill's directory (built-ins cannot be removed)."""
        st = self._skill_state(name)
        if st.get("builtin"):
            raise ValueError("built-in skills cannot be removed — disable them instead")
        self.disable(name)
        self._manifests.pop(name, None)
        self._state["skills"].pop(name, None)
        # remove tool index entries owned by this skill
        for t, owner in list(self._tool_index.items()):
            if owner == name:
                self._tool_index.pop(t, None)
        skill_dir = self.custom_dir / name
        if skill_dir.is_dir():
            self.disabled_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            target = self.disabled_dir / name
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.move(str(skill_dir), str(target))
        self.save_state()

    # ── queries ─────────────────────────────────────────────────────────────
    def is_enabled(self, name: str) -> bool:
        return bool(self._skill_state(name).get("enabled"))

    def is_known(self, name: str) -> bool:
        return name in self._builtin or name in self._manifests or name in self._state["skills"]

    def skill_for_tool(self, tool_name: str) -> Optional[str]:
        return self._tool_index.get(tool_name)

    def granted(self, name: str) -> list[str]:
        return list(self._skill_state(name).get("permissions_granted", []))

    def all_names(self) -> list[str]:
        names = set(self._builtin) | set(self._manifests) | set(self._state["skills"])
        return sorted(names)

    def summary(self) -> list[dict]:
        out = []
        for name in self.all_names():
            st = self._skill_state(name)
            skill = self._loaded.get(name) or self._builtin.get(name)
            manifest = self._manifests.get(name)
            out.append({
                "name": name,
                "enabled": bool(st.get("enabled")),
                "builtin": bool(st.get("builtin")),
                "tools": st.get("tools") or (skill.tool_names() if skill else [t.name for t in manifest.tools] if manifest else []),
                "permissions": skill.permissions if skill else (manifest.permissions if manifest else []),
                "granted": st.get("permissions_granted", []),
                "failure_count": st.get("failure_count", 0),
                "quarantined": bool(st.get("quarantined", False)),
            })
        return out
