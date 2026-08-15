# -*- coding: utf-8 -*-
"""
SkillBuilder — generates a new skill from a natural-language request.

Given "add Spotify control", it asks Gemini to produce:

    * a valid ``SkillManifest`` (name, tools + schemas, permissions, deps)
    * a complete ``skill.py`` module implementing ``class Skill(SkillBase)``

The generated code is constrained to a safe contract: it may only import the
standard library, the ``skills.base`` interface, existing ``actions/*`` helpers,
or packages it explicitly lists in ``manifest.dependencies`` (installed safely
before the skill is ever executed).
"""

from __future__ import annotations

import json
import re
from typing import Callable, Optional


_GENERATION_PROMPT = """You are the JARVIS skill generator. Turn a user request into a working JARVIS skill.

USER REQUEST: {request}
SUGGESTED SKILL NAME: {name}

Produce a JSON object with exactly two string fields:

1. "manifest" — a skill manifest object with these keys:
   - "name": the skill name (lowercase snake_case, e.g. "spotify")
   - "display_name": a human label
   - "description": one sentence explaining what the skill does and WHEN to use it
   - "version": "1.0.0"
   - "permissions": an array chosen ONLY from: {permissions}
   - "dependencies": an array of pip package names (empty list if none)
   - "config": an object of default config values
   - "tools": an array of tool objects. Each tool object has:
       * "name": the Gemini function name (snake_case, e.g. "spotify_control")
       * "description": a detailed description telling JARVIS exactly when to call
         this tool and what it does
       * "parameters": a Gemini function-calling OBJECT schema with "type": "OBJECT",
         "properties": {{...}} and "required": [...]

2. "code" — a COMPLETE Python module implementing the skill. Rules:
   - It MUST subclass the provided base and override handle().
   - Start with: from skills.base import Skill as SkillBase, SkillContext, SkillTestResult
   - Define: class Skill(SkillBase):
       name = "<name>"
       display_name = "<display name>"
       description = "<description>"
       permissions = [ ... ]          # same as manifest
       dependencies = [ ... ]         # same as manifest
       config = {{ ... }}
       def handle(self, tool_name, args, context):
           ...  # dispatch on tool_name, return a plain string result
       def self_test(self, context):
           ...  # a lightweight, non-destructive smoke test; return SkillTestResult(ok=True, message="...")
   - Use ONLY the standard library, existing "actions.*" helpers (import them inside
     the function if needed), or packages declared in dependencies.
   - Never use shell=True, never touch files outside the project, never print secrets.
   - Wrap risky operations in try/except and return a clear message string.

Return ONLY the JSON object (no markdown fences, no commentary)."""


class SkillBuilder:
    """Generates skills via the Gemini API already used by the app."""

    def __init__(self, api_key: Callable[[], str]):
        self._api_key = api_key

    def generate(self, request: str, name: str) -> tuple[dict, str]:
        """Return ``(manifest_dict, code_str)`` for the requested skill."""
        from skills.permissions import KNOWN_PERMISSIONS

        prompt = _GENERATION_PROMPT.format(
            request=request,
            name=name,
            permissions=", ".join(sorted(KNOWN_PERMISSIONS)),
        )

        api_key = self._api_key() or ""
        if not api_key:
            raise RuntimeError("no API key available — cannot generate a skill")

        from google import genai
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = (resp.text or "").strip()
        return self._parse(text)

    @staticmethod
    def _parse(text: str) -> tuple[dict, str]:
        """Extract the JSON object from a (possibly noisy) model response."""
        text = text.strip()
        # strip markdown fences if present
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        # take from first { to last }
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("model response did not contain a JSON object")
        data = json.loads(text[start : end + 1])
        manifest = data.get("manifest")
        code = data.get("code")
        if not isinstance(manifest, dict) or not isinstance(code, str) or not code.strip():
            raise ValueError("model response missing 'manifest' or 'code'")
        return manifest, code


def sanitize_name(raw: str) -> str:
    """Turn arbitrary text into a safe skill identifier."""
    name = re.sub(r"[^a-z0-9_]+", "_", raw.strip().lower())
    name = re.sub(r"_+", "_", name).strip("_")
    return name[:40] or "custom_skill"
