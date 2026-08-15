# -*- coding: utf-8 -*-
"""
Skill test harness.

Runs a sequence of non-destructive checks against a skill before it is enabled:

    1. import        — the skill module imports cleanly in isolation
    2. schema        — every declared tool has a valid Gemini schema
    3. permissions   — only known permissions are declared
    4. dependencies  — declared pip packages are importable (or installable)
    5. self_test     — the skill's own smoke test passes

A skill that fails any check is never registered/enabled — it is quarantined.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Optional

from skills.base import Skill, SkillContext, SkillTestResult


def _import_module_from_file(module_name: str, file_path: Path):
    """Import a module from an arbitrary path without polluting sys.path."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module spec for {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_skill(
    skill: Skill,
    skill_dir: Optional[Path] = None,
    entrypoint: str = "skill.py",
    context: Optional[SkillContext] = None,
    install_missing: bool = False,
) -> SkillTestResult:
    """Validate ``skill`` and return a detailed result.

    When ``skill_dir`` is provided, the module is imported from disk first
    (isolation check). ``checks`` maps each check name to a boolean; the result
    message is a concise human-readable summary.
    """
    ctx = context or SkillContext()
    checks: dict = {}
    details: dict = {}

    # 1) import isolation (only for on-disk skills)
    if skill_dir is not None:
        try:
            _import_module_from_file(
                f"_jarvis_skill_test_{skill.name}", skill_dir / entrypoint
            )
            checks["import"] = True
            details["import"] = "ok"
        except Exception as e:  # noqa: BLE001
            return SkillTestResult(
                ok=False, message=f"import failed: {e}", checks={"import": str(e)}
            )
    else:
        checks["import"] = True

    # 2) schema
    schema_errors: list[str] = []
    for tool in skill.tools:
        if not tool.name:
            schema_errors.append("tool with empty name")
            continue
        params = tool.parameters or {}
        if not isinstance(params, dict):
            schema_errors.append(f"tool '{tool.name}' parameters must be a dict")
            continue
        props = params.get("properties", {}) or {}
        required = params.get("required", []) or []
        for r in required:
            if r not in props:
                schema_errors.append(f"tool '{tool.name}' requires '{r}' but it is not in properties")
    checks["schema"] = not schema_errors
    details["schema"] = "ok" if not schema_errors else "; ".join(schema_errors)

    # 3) permissions
    from skills.permissions import validate_permissions
    ok_perm, unknown = validate_permissions(skill.permissions)
    checks["permissions"] = ok_perm
    details["permissions"] = "ok" if ok_perm else f"unknown: {unknown}"

    # 4) dependencies
    if skill.dependencies:
        from skills.dependencies import missing_packages
        missing = missing_packages(skill.dependencies)
        if missing:
            if install_missing:
                from skills.dependencies import install
                ok_dep, msg = install(missing, auto_install=True)
                checks["dependencies"] = ok_dep
                details["dependencies"] = msg
            else:
                checks["dependencies"] = False
                details["dependencies"] = "missing (not installed): " + ", ".join(missing)
        else:
            checks["dependencies"] = True
            details["dependencies"] = "ok"
    else:
        checks["dependencies"] = True
        details["dependencies"] = "ok (none)"

    # 5) self_test (only if every static check passed)
    static_ok = all(checks.get(k, True) for k in ("import", "schema", "permissions", "dependencies"))
    if static_ok:
        try:
            st = skill.self_test(ctx)
            checks["self_test"] = bool(st.ok)
            details["self_test"] = st.message or ("ok" if st.ok else "failed")
            if not st.ok:
                return SkillTestResult(
                    ok=False, message=f"self_test failed: {st.message}", checks=details
                )
        except Exception as e:  # noqa: BLE001
            return SkillTestResult(
                ok=False, message=f"self_test raised: {e}", checks=details
            )
    else:
        checks["self_test"] = False
        details["self_test"] = "skipped (static checks failed)"

    all_ok = all(checks.values())
    return SkillTestResult(
        ok=all_ok,
        message="all checks passed" if all_ok else "checks failed: " + "; ".join(
            f"{k}={v}" for k, v in details.items()
        ),
        checks=details,
    )
