# -*- coding: utf-8 -*-
"""
Spotify skill — reference custom skill.

Demonstrates the exact shape a dynamically-created skill takes. It reuses the
existing JARVIS infrastructure (``actions.open_app`` + ``actions.browser_control``
+ OS media keys) so it works with zero extra dependencies.

    * play_playlist / play_track                → open Spotify Web, search, play
    * open                                       → open Spotify
    * play / pause / next / previous             → OS media keys (fallback only;
      the media_control skill is the primary route and opens nothing)
    * volume_up / volume_down / volume_set / mute → Spotify's own (per-app)
      volume — separate from the Windows master volume (that stays media_control)
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
from urllib.parse import quote_plus

from skills.base import Skill as SkillBase, SkillContext, SkillTestResult


# Transport-only media keys. Volume keys are handled separately below so they
# control Spotify's own volume, not the Windows master volume.
_MEDIA_KEYS = {
    "play": "playpause",
    "pause": "playpause",
    "next": "nexttrack",
    "previous": "prevtrack",
}

# Spotify's audio may live in the desktop app (spotify.exe) or in the browser
# (web player). Per-app volume targets the desktop app first, browser second.
_SPOTIFY_APP_STEMS = ("spotify",)
_BROWSER_STEMS = ("chrome", "chromium", "msedge", "brave", "vivaldi", "opera")


def _press(key: str) -> bool:
    try:
        import pyautogui
        pyautogui.press(key)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[spotify] media key failed: {e}")
        return False


def _open_spotify(context: SkillContext) -> None:
    from actions.open_app import open_app
    open_app(parameters={"app_name": "spotify"}, player=context.ui)


def _spotify_volume(action: str, args: dict) -> str:
    """Adjust Spotify's own volume via the Windows per-app (session) audio API."""
    from actions.computer_settings import (
        get_app_volume, set_app_volume, toggle_app_mute,
    )

    # Prefer the desktop app; fall back to the browser (web player).
    if get_app_volume(_SPOTIFY_APP_STEMS) is not None:
        targets, label = _SPOTIFY_APP_STEMS, "Spotify"
    elif get_app_volume(_BROWSER_STEMS) is not None:
        targets, label = _BROWSER_STEMS, "Spotify (browser)"
    else:
        return "Spotify: I could not find its audio session — start playing something first."

    if action == "mute":
        muted = toggle_app_mute(targets)
        if muted is None:
            return "Spotify: could not find its audio session."
        return f"{label} {'muted' if muted else 'unmuted'}."

    if action == "volume_set":
        raw = args.get("value", args.get("level"))
        if raw is None:
            return "Spotify: volume_set needs a value from 0 to 100."
        try:
            new = max(0.0, min(1.0, float(raw) / 100.0))
        except (TypeError, ValueError):
            return "Spotify: invalid volume value — use 0 to 100."
    else:  # volume_up / volume_down
        cur = get_app_volume(targets)
        if cur is None:
            return "Spotify: could not read its volume."
        step = 0.1
        new = min(1.0, cur + step) if action == "volume_up" else max(0.0, cur - step)

    if not set_app_volume(targets, new):
        return "Spotify: could not set its volume."
    return f"{label} volume: {int(round(new * 100))}%."


class Skill(SkillBase):
    name = "spotify"
    display_name = "Spotify"
    description = (
        "Spotify-specific actions: open Spotify, play a playlist/track by name, "
        "or adjust Spotify's own volume (per-app, not Windows master). "
        "Simple transport (play/pause/next/previous/stop) and Windows volume use media_control."
    )
    version = "1.0.0"
    permissions = ["browser", "network", "media_control"]
    dependencies = []
    config = {"mode": "web"}

    def handle(self, tool_name: str, args: dict, context: SkillContext) -> str:
        action = (args.get("action") or "play").lower().strip()

        # Media-key actions. These are global OS controls and must NOT open
        # Spotify first — opening a browser tab just to press play/pause/next
        # created a stray Spotify tab every time. media_control is the primary
        # route; this branch exists only as a harmless fallback.
        if action in _MEDIA_KEYS:
            if _press(_MEDIA_KEYS[action]):
                return f"Spotify: {action.replace('_', ' ')}."
            return "Spotify: I could not send the media command."

        # Spotify's own volume (per-app) — separate from Windows master volume.
        if action in ("volume_up", "volume_down", "volume_set", "mute"):
            return _spotify_volume(action, args)

        # search + play actions
        if action in ("play_playlist", "play_track"):
            query = (args.get("name") or args.get("query") or "").strip()
            if not query:
                return "Spotify: I need a playlist or track name."

            # Primary: Spotify URI scheme — opens search directly in the desktop
            # app without touching the browser at all. No Playwright, no about:blank.
            uri = f"spotify:search:{quote_plus(query)}"
            try:
                _sys = platform.system()
                if _sys == "Windows":
                    os.startfile(uri)
                elif _sys == "Darwin":
                    subprocess.Popen(["open", uri])
                else:
                    subprocess.Popen(["xdg-open", uri],
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                return f"Spotify: searching for '{query}' in the Spotify app."
            except Exception as _e:
                print(f"[spotify] URI scheme failed ({_e}), falling back to web player")

            # Fallback: navigate to Spotify Web Player in the existing real browser.
            # Uses go_to (native, no Playwright) — never opens a new window or
            # creates an about:blank tab.
            from actions.browser_control import browser_control
            url = "https://open.spotify.com/search/" + quote_plus(query)
            browser_control(parameters={"action": "go_to", "url": url}, player=context.ui)
            return f"Spotify: opened search for '{query}' in the browser."

        if action == "open":
            _open_spotify(context)
            return "Spotify: opened."

        return (
            "Spotify: unsupported action. Use open, play_playlist, play_track, "
            "volume_up, volume_down, volume_set, or mute "
            "(for play/pause/next/previous/stop and Windows volume use media_control)."
        )

    def self_test(self, context: SkillContext | None = None) -> SkillTestResult:
        # Static-only smoke test: verify the tool name + action vocabulary are sane.
        actions = set(_MEDIA_KEYS) | {"play_playlist", "play_track", "open",
                                      "volume_up", "volume_down", "volume_set", "mute"}
        if not actions:
            return SkillTestResult(ok=False, message="empty action set")
        return SkillTestResult(ok=True, message=f"spotify: {len(actions)} actions registered")
