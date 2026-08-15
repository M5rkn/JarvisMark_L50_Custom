# -*- coding: utf-8 -*-
"""
SkillManager — the orchestrator behind JARVIS's skill system.

Responsibilities (all five of the required capabilities):

    detect      — match a user request to the most likely skill
    load/use    — route a tool call to the owning skill, with permission checks
    create      — generate a brand-new skill from a natural-language request
    install     — install a new skill's dependencies safely
    test        — validate + smoke-test the new skill before enabling it
    register    — enable the skill automatically after it passes testing
    disable     — quarantine / disable broken skills without touching the rest

A skill that fails repeatedly is auto-disabled (quarantined) after a threshold,
so one broken skill can never take JARVIS down.
"""

from __future__ import annotations

import re
import traceback
from pathlib import Path
from typing import Callable, Optional

from skills.base import Skill, SkillContext, SkillError
from skills.builder import SkillBuilder, sanitize_name
from skills.manifest import SkillManifest, ToolSpec
from skills.registry import SkillRegistry
from skills.tester import test_skill


class SkillManager:
    AUTO_DISABLE_THRESHOLD = 3   # consecutive failures before a skill is disabled

    def __init__(
        self,
        base_dir: Path,
        ui=None,
        speak: Optional[Callable[[str], None]] = None,
        api_key: Optional[Callable[[], str]] = None,
    ):
        self.context = SkillContext(
            ui=ui,
            speak=speak or (lambda text: None),
            api_key=api_key or (lambda: ""),
            base_dir=base_dir,
        )
        self.registry = SkillRegistry(base_dir, self.context)
        self.builder = SkillBuilder(self.context.api_key)

        # Register built-in skills (these wrap the existing actions/ module).
        from skills.builtin import BUILTIN_SKILLS
        for skill in BUILTIN_SKILLS:
            self.registry.register_builtin(skill)

        # Discover user-created skills on disk (manifests only — no code runs).
        self.registry.discover_custom()
        self.registry.save_state()

        # Warm-load every enabled skill so a broken custom skill surfaces at
        # startup (and gets quarantined) rather than mid-conversation.
        for name in self.registry.all_names():
            if self.registry.is_enabled(name):
                try:
                    self.registry.load(name)
                except Exception as e:  # noqa: BLE001
                    print(f"[Skills] ⚠️ failed to load enabled skill '{name}': {e}")
                    self.registry.disable(name, quarantine=True)

    # ── Gemini tool declarations ────────────────────────────────────────────
    def tool_declarations(self) -> list[dict]:
        """Return function_declarations for every ENABLED skill's tools."""
        decls: list[dict] = []
        for name in self.registry.all_names():
            if not self.registry.is_enabled(name):
                continue
            try:
                skill = self.registry.load(name)
            except Exception as e:  # noqa: BLE001
                print(f"[Skills] ⚠️ could not build declarations for '{name}': {e}")
                continue
            for tool in skill.tools:
                decls.append(tool.declaration())
        return decls

    # ── detection ───────────────────────────────────────────────────────────
    def match(self, request: str) -> Optional[str]:
        """Return the best skill name for a free-text request, or None.

        Primary routing is handled by Gemini's function calling; this is a
        deterministic fallback used by create_skill (to avoid duplicates) and
        by inspection tooling.
        """
        request = (request or "").lower()
        best_name, best_score = None, -1
        for info in self.registry.summary():
            hay = " ".join([
                info["name"],
                *info["tools"],
            ]).lower()
            score = 0
            for token in re.findall(r"[a-z0-9_]+", request):
                if token in info["name"]:
                    score += 3
                if token in hay:
                    score += 1
            if score > best_score:
                best_name, best_score = info["name"], score
        return best_name if best_score > 0 else None

    # ── ownership / execution ───────────────────────────────────────────────
    def handles(self, tool_name: str) -> bool:
        """True if any known skill (enabled or not) owns this tool name.

        Returning True for disabled skills is deliberate: a disabled skill must
        fail loudly (with a clear message) instead of silently falling through
        to legacy handling and running anyway.
        """
        return self.registry.skill_for_tool(tool_name) is not None

    def run(self, tool_name: str, args: dict) -> str:
        """Execute a skill tool. Raises SkillError on any problem."""
        name = self.registry.skill_for_tool(tool_name)
        if name is None:
            raise SkillError(f"no skill owns tool '{tool_name}'")

        if not self.registry.is_enabled(name):
            raise SkillError(f"skill '{name}' is disabled")

        skill = self.registry.load(name)   # may raise if code is broken

        missing = [p for p in skill.permissions if p not in self.registry.granted(name)]
        if missing:
            raise SkillError(f"skill '{name}' is missing granted permissions: {', '.join(missing)}")

        try:
            result = skill.run(tool_name, args, self.context)
            self._on_success(name)
            return result or "Done."
        except SkillError:
            raise
        except Exception as e:  # noqa: BLE001
            self._on_failure(name)
            raise SkillError(f"{name}: {e}") from e

    def _on_success(self, name: str) -> None:
        st = self.registry._skill_state(name)
        if st.get("failure_count"):
            st["failure_count"] = 0
            self.registry.save_state()

    def _on_failure(self, name: str) -> None:
        st = self.registry._skill_state(name)
        st["failure_count"] = int(st.get("failure_count", 0)) + 1
        if st["failure_count"] >= self.AUTO_DISABLE_THRESHOLD:
            print(f"[Skills] 🚫 auto-disabling '{name}' after {st['failure_count']} consecutive failures")
            self.registry.disable(name, quarantine=True)
        else:
            self.registry.save_state()

    # ── lifecycle commands ──────────────────────────────────────────────────
    def list_skills(self) -> str:
        rows = self.registry.summary()
        if not rows:
            return "No skills installed."
        lines = ["Installed skills:"]
        for r in rows:
            if r["enabled"]:
                state = "enabled"
            elif r["quarantined"]:
                state = "quarantined"
            else:
                state = "disabled"
            tools = ", ".join(r["tools"]) or "-"
            lines.append(f"  {r['name']} [{state}] tools: {tools}")
        return "\n".join(lines)

    def skill_status(self, name: str) -> str:
        name = sanitize_name(name)
        info = next((r for r in self.registry.summary() if r["name"] == name), None)
        if not info:
            return f"Unknown skill '{name}'."
        return (
            f"Skill '{name}': {'enabled' if info['enabled'] else 'disabled'}, "
            f"tools={info['tools']}, permissions={info['permissions']}, "
            f"granted={info['granted']}, failures={info['failure_count']}"
        )

    def disable_skill(self, name: str) -> str:
        name = sanitize_name(name)
        if not self.registry.is_known(name):
            return f"Unknown skill '{name}'."
        self.registry.disable(name, quarantine=False)
        return f"Skill '{name}' disabled."

    def enable_skill(self, name: str, grant_permissions: Optional[list[str]] = None) -> str:
        name = sanitize_name(name)
        if not self.registry.is_known(name):
            return f"Unknown skill '{name}'."
        skill = self.registry.load(name)
        self.registry.enable(name, grant_permissions=grant_permissions)
        return f"Skill '{name}' enabled."

    def remove_skill(self, name: str) -> str:
        name = sanitize_name(name)
        if not self.registry.is_known(name):
            return f"Unknown skill '{name}'."
        try:
            self.registry.remove(name)
            return f"Skill '{name}' removed."
        except ValueError as e:
            return str(e)

    # ── dynamic creation ────────────────────────────────────────────────────
    def create_skill(
        self,
        description: str,
        name: Optional[str] = None,
        auto_approve: bool = True,
        auto_install: bool = True,
    ) -> str:
        """Full pipeline: generate → write → install deps → test → register.

        Returns a human-readable status string for JARVIS to speak.
        """
        description = (description or "").strip()
        if not description:
            return "I need a description of the capability to add."

        # Reuse an existing skill if the request already maps to one.
        existing = self.match(description)
        if existing:
            if self.registry.is_enabled(existing):
                return f"A skill for this already exists ('{existing}') and is enabled."
            self.registry.enable(existing)
            return f"A skill for this already exists ('{existing}') — re-enabled it."

        name = sanitize_name(name) if name else self._propose_name(description)
        self.context.log(f"[Skills] 🧬 creating skill '{name}' from: {description}")

        try:
            manifest_dict, code = self.builder.generate(description, name)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return f"I could not generate the '{name}' skill: {e}"

        try:
            manifest = self._manifest_from_dict(manifest_dict, fallback_name=name)
        except Exception as e:  # noqa: BLE001
            return f"Generated skill is invalid: {e}"

        skill_dir = self.registry.custom_dir / manifest.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        manifest.dump(skill_dir / "manifest.json")
        (skill_dir / manifest.entrypoint).write_text(code, encoding="utf-8")

        # 1) register the manifest in the registry (not yet enabled) so that any
        #    later failure can quarantine a *known* skill.
        self.registry._manifests[manifest.name] = manifest
        st = self.registry._skill_state(manifest.name)
        st.update({
            "enabled": False,
            "builtin": False,
            "tools": [t.name for t in manifest.tools],
            "permissions_granted": [],
            "failure_count": 0,
            "config": dict(manifest.config),
            "quarantined": False,
        })
        for t in manifest.tools:
            self.registry._tool_index.setdefault(t.name, manifest.name)

        # 2) install dependencies safely
        if manifest.dependencies:
            from skills.dependencies import install
            ok, msg = install(manifest.dependencies, auto_install=auto_install)
            if not ok:
                self.registry.disable(manifest.name, quarantine=True)
                return f"Skill '{manifest.name}' was created but its dependencies could not be installed: {msg}"

        # 3) load + test
        try:
            skill = self.registry.load(manifest.name)
        except Exception as e:  # noqa: BLE001
            self.registry.disable(manifest.name, quarantine=True)
            return f"Skill '{manifest.name}' was created but failed to load: {e}"

        result = test_skill(
            skill,
            skill_dir=skill_dir,
            entrypoint=manifest.entrypoint,
            context=self.context,
            install_missing=auto_install,
        )
        if not result.ok:
            self.registry.disable(manifest.name, quarantine=True)
            return (
                f"Skill '{manifest.name}' was created but failed testing and has been quarantined: "
                f"{result.message}"
            )

        # 4) register (enable) — grant declared permissions on explicit request
        grant = manifest.permissions if auto_approve else []
        self.registry.enable(manifest.name, grant_permissions=grant)
        self.registry.save_state()
        self.context.log(f"[Skills] ✅ '{manifest.name}' created, tested and enabled.")
        return (
            f"Done, sir — the '{manifest.name}' skill is ready. "
            f"It provides: {', '.join(t.name for t in manifest.tools)}."
        )

    def _manifest_from_dict(self, data: dict, fallback_name: str) -> SkillManifest:
        data = dict(data)
        name = sanitize_name(data.get("name") or fallback_name)
        tools = []
        for t in data.get("tools", []):
            tools.append(ToolSpec(
                name=t.get("name", ""),
                description=t.get("description", ""),
                parameters=t.get("parameters", {"type": "OBJECT", "properties": {}}),
            ))
        manifest = SkillManifest(
            name=name,
            display_name=data.get("display_name", name),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            entrypoint=data.get("entrypoint", "skill.py"),
            class_name=data.get("class_name", "Skill"),
            permissions=list(data.get("permissions", [])),
            dependencies=list(data.get("dependencies", [])),
            config=dict(data.get("config", {})),
            config_schema=dict(data.get("config_schema", {})),
            tools=tools,
        )
        ok, errors = manifest.validate()
        if not ok:
            raise ValueError("; ".join(errors))
        return manifest

    @staticmethod
    def _propose_name(text: str) -> str:
        _STOP = {
            "add", "a", "an", "the", "for", "my", "and", "or", "to", "of", "in",
            "on", "with", "new", "skill", "plugin", "feature", "support", "control",
            "integration", "please", "jarvis", "create", "make", "build", "install",
        }
        words = re.findall(r"[a-z0-9]+", text.lower())
        nouns = [w for w in words if w not in _STOP and len(w) > 2]
        if nouns:
            return sanitize_name(nouns[0])
        return sanitize_name(words[-1] if words else "custom_skill")
