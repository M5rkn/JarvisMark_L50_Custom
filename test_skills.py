# -*- coding: utf-8 -*-
"""
Smoke test for the JARVIS Skills/Plugins framework.

Runs WITHOUT the voice engine / Gemini / PyQt — it exercises only the skills
package (pure stdlib at import time) to verify:

    * built-in skills register and expose their tools
    * dynamic tool declarations are built correctly (enabled skills only)
    * routing ownership is correct (skill tools vs. core tools)
    * the custom Spotify skill loads and passes validation + self-test
    * the skill-creation helpers (naming, manifest parsing) behave

Run:  python test_skills.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))


class _FakeUI:
    muted = False
    current_file = None

    def write_log(self, text):
        pass

    def show_content(self, label, text):
        pass

    def set_state(self, state):
        pass


def _fake_speak(text):
    pass


def main() -> int:
    failures = 0

    def check(label, cond, extra=""):
        nonlocal failures
        status = "PASS" if cond else "FAIL"
        print(f"[{status}] {label}" + (f" — {extra}" if extra else ""))
        if not cond:
            failures += 1

    from skills.manager import SkillManager
    from skills.builder import sanitize_name
    from skills.tester import test_skill

    manager = SkillManager(
        base_dir=BASE_DIR,
        ui=_FakeUI(),
        speak=_fake_speak,
        api_key=lambda: "",
    )

    print("\n== built-in skills ==")
    builtin = sorted(manager.registry._builtin.keys())
    expected = {"browser", "coding", "files", "youtube", "telegram", "system", "research", "finance", "media"}
    check("9 built-in skills registered", builtin == sorted(expected), str(builtin))

    print("\n== tool declarations ==")
    decls = manager.tool_declarations()
    names = {d["name"] for d in decls}
    for t in ["browser_control", "open_app", "web_search", "code_helper",
              "file_controller", "youtube_video", "send_message", "system_status",
              "spotify_control", "media_control", "finance", "flight_finder"]:
        check(f"tool '{t}' exposed", t in names)
    check("core tool 'get_current_time' NOT in skill decls", "get_current_time" not in names)
    check("core tool 'save_memory' NOT in skill decls", "save_memory" not in names)

    print("\n== routing ownership ==")
    check("handles('browser_control')", manager.handles("browser_control") is True)
    check("handles('spotify_control')", manager.handles("spotify_control") is True)
    check("does NOT handle 'get_current_time'", manager.handles("get_current_time") is False)
    check("does NOT handle 'add_skill'", manager.handles("add_skill") is False)

    print("\n== disable/isolation ==")
    manager.disable_skill("browser")
    check("browser disabled", manager.registry.is_enabled("browser") is False)
    check("browser tool removed from decls after disable",
          "browser_control" not in {d["name"] for d in manager.tool_declarations()})
    manager.enable_skill("browser")
    check("browser re-enabled", manager.registry.is_enabled("browser") is True)

    print("\n== custom Spotify skill ==")
    spotify = manager.registry.load("spotify")
    st = spotify.self_test(manager.context)
    check("spotify self_test passes", st.ok, st.message)
    manifest = manager.registry._manifests["spotify"]
    result = test_skill(
        spotify,
        skill_dir=BASE_DIR / "skills" / "custom" / "spotify",
        entrypoint=manifest.entrypoint,
        context=manager.context,
        install_missing=False,
    )
    check("spotify test_skill passes", result.ok, result.message)

    print("\n== creation helpers ==")
    check("sanitize_name('Spotify Control')", sanitize_name("Spotify Control") == "spotify_control", sanitize_name("Spotify Control"))
    check("propose_name('add Spotify control')",
          SkillManager._propose_name("add Spotify control") == "spotify",
          SkillManager._propose_name("add Spotify control"))

    m = manager._manifest_from_dict({
        "name": "demo", "description": "demo skill", "version": "1.0.0",
        "permissions": ["network"], "dependencies": [],
        "tools": [{"name": "demo_tool", "description": "does things",
                   "parameters": {"type": "OBJECT", "properties": {}, "required": []}}],
    }, fallback_name="demo")
    check("_manifest_from_dict validates", m.name == "demo" and len(m.tools) == 1, m.name)

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
