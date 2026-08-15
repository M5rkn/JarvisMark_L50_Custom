# -*- coding: utf-8 -*-
"""
Media skill — hardware/media-key playback control.

Sends OS media keys (play/pause, next, previous, stop, volume) so JARVIS can
control whatever is currently playing (Spotify, YouTube, a local player) without
needing app-specific integration. Zero new dependencies (uses ``pyautogui``).
"""

from skills.base import Skill, Tool, SkillTestResult

_KEYMAP = {
    "play": "playpause",
    "pause": "playpause",
    "play_pause": "playpause",
    "toggle": "playpause",
    "next": "nexttrack",
    "previous": "prevtrack",
    "prev": "prevtrack",
    "stop": "stopmedia",
    "volume_up": "volumeup",
    "volume_down": "volumedown",
    "mute": "volumemute",
}


def _handle(args, context):
    action = (args.get("action") or "").lower().strip()
    key = _KEYMAP.get(action)
    if not key:
        return (
            "Unsupported media action. Use one of: "
            + ", ".join(sorted(set(_KEYMAP)))
        )

    try:
        import pyautogui
        pyautogui.press(key)
    except Exception as e:  # noqa: BLE001
        return f"Could not send media key '{key}': {e}"

    label = action.replace("_", " ")
    return f"Sent media command: {label}."


skill = Skill()
skill.name = "media"
skill.display_name = "Media"
skill.description = "Controls media playback via OS media keys (play, pause, next, previous, volume)."
skill.permissions = ["media_control"]
skill.tools = [
    Tool(
        name="media_control",
        description=(
            "Controls whatever media is currently playing on the computer using OS media keys. "
            "Use for play, pause, next track, previous track, stop, volume up/down, mute — "
            "for any active media (Spotify, YouTube, music player, video). "
            "This does NOT select a specific track/playlist; it controls the active playback."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | pause | play_pause | next | previous | stop | volume_up | volume_down | mute"},
            },
            "required": ["action"],
        },
        handler=_handle,
    )
]
