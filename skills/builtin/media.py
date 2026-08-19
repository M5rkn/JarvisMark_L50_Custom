# -*- coding: utf-8 -*-
"""
Media skill — hardware/media-key playback control.

Sends OS media keys (play/pause, next, previous, volume) so JARVIS can control
whatever is currently playing (Spotify, YouTube, a local player) without needing
app-specific integration. Zero new dependencies (uses ``pyautogui`` + ``pycaw``).

``play``/``start``/``resume`` and ``pause`` are *state-aware*: Windows
only exposes a single play/pause toggle key (``VK_MEDIA_PLAY_PAUSE``), so we
sample the running audio sessions to decide whether anything is actually playing
before toggling. That way "start" never accidentally pauses music that is already
playing, and "pause" never restarts music that is already paused. ``stop`` sends
the dedicated OS stop key, preserving its distinct semantics.
"""

import os
import sys
import time

from skills.base import Skill, Tool, SkillTestResult

# Actions that mean "make it play" — only toggle if nothing is currently playing.
_PLAY_ACTIONS = {"play", "start", "resume", "unpause"}
# Actions that mean "make it pause" — only toggle if something is currently playing.
_PAUSE_ACTIONS = {"pause", "halt"}
_STOP_ACTIONS = {"stop"}

# Non-state-aware actions: map straight onto a pyautogui media key.
_KEYMAP = {
    "play_pause":  "playpause",
    "toggle":      "playpause",
    "next":        "nexttrack",
    "previous":    "prevtrack",
    "prev":        "prevtrack",
    "volume_up":   "volumeup",
    "volume_down": "volumedown",
    "mute":        "volumemute",
}

# Peak level (0.0-1.0) above which an audio session counts as "playing".
_PLAYING_PEAK = 0.01


def _is_audio_playing() -> bool | None:
    """True if any non-JARVIS audio session is currently emitting sound.

    Returns None when the state cannot be determined (non-Windows or pycaw
    unavailable), so callers can fall back to a plain toggle.
    """
    if sys.platform != "win32":
        return None
    try:
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation

        me = os.getpid()
        # Collect every other process's audio meter once, then sample it a few
        # times — a single instant can land in a quiet passage of a song.
        meters = []
        for s in AudioUtilities.GetAllSessions():
            try:
                if s.ProcessId in (0, me):
                    continue
                meters.append(s._ctl.QueryInterface(IAudioMeterInformation))
            except Exception:
                continue

        for _ in range(3):
            for meter in meters:
                try:
                    if float(meter.GetPeakValue()) > _PLAYING_PEAK:
                        return True
                except Exception:
                    continue
            time.sleep(0.03)
        return False
    except Exception as e:
        print(f"[media] playback-state check failed: {e}")
        return None


def _press(key: str, label: str) -> str:
    try:
        import pyautogui
        pyautogui.press(key)
    except Exception as e:  # noqa: BLE001
        return f"Could not send media key '{key}': {e}"
    return f"Sent media command: {label}."


def _handle(args, context):
    action = (args.get("action") or "").lower().strip()

    # State-aware start/pause: avoid the play/pause toggle acting backwards.
    if action in _PLAY_ACTIONS:
        if _is_audio_playing() is True:
            return "Media is already playing."
        return _press("playpause", "play")
    if action in _PAUSE_ACTIONS:
        if _is_audio_playing() is False:
            return "Media is already stopped."
        return _press("playpause", "pause")
    if action in _STOP_ACTIONS:
        return _press("stopmedia", "stop")

    key = _KEYMAP.get(action)
    if not key:
        return (
            "Unsupported media action. Use one of: "
            + ", ".join(sorted(set(_KEYMAP) | _PLAY_ACTIONS | _PAUSE_ACTIONS | _STOP_ACTIONS))
        )

    return _press(key, action.replace("_", " "))


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
            "Use for play/start/resume, pause/stop, next track, previous track, volume up/down, mute — "
            "for any active media (Spotify, YouTube, music player, video). "
            "play/start/resume only start playback when it is stopped; pause/stop only halt it "
            "when it is playing — they never toggle backwards. "
            "This does NOT select a specific track/playlist; it controls the active playback."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | start | resume | pause | stop | play_pause (toggle) | next | previous | volume_up | volume_down | mute"},
            },
            "required": ["action"],
        },
        handler=_handle,
    )
]
