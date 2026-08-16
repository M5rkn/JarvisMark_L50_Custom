# -*- coding: utf-8 -*-
"""
Work Mode ("Рабочий режим") — a deterministic multi-step startup sequence.

Triggered when the user says "work mode" / "рабочий режим". It opens VS Code,
opens Spotify in the browser and resumes the last paused track, opens a terminal
and types "qwen", and opens ChatGPT — then reports what happened. Each step is
best-effort and isolated, so one failure never aborts the rest.
"""

import time
import platform

_OS = platform.system()


def _resume_playback() -> str:
    """Resume whatever media was last playing (Spotify, etc.) via the OS key."""
    try:
        import pyautogui
        pyautogui.press("playpause")
        return "resumed last track"
    except Exception as e:
        return f"could not resume playback: {e}"


def _type_in_terminal(text: str) -> str:
    """Paste/type ``text`` into the focused terminal and press Enter."""
    try:
        from actions.computer_settings import type_text
        type_text(text, press_enter_after=True)
        return f"typed '{text}'"
    except Exception as e:
        return f"could not type '{text}': {e}"


def work_mode(parameters=None, response=None, player=None, session_memory=None) -> str:
    from actions.open_app import open_app

    def _open(app: str) -> str:
        try:
            return open_app(parameters={"app_name": app}, player=player)
        except Exception as e:
            return f"could not open {app}: {e}"

    summary = []

    # 1) VS Code
    if player:
        player.write_log("[work_mode] opening VS Code")
    summary.append("VS Code: " + _open("visual studio code"))
    time.sleep(1.0)

    # 2) Spotify in the browser + resume the last paused track
    if player:
        player.write_log("[work_mode] opening Spotify")
    summary.append("Spotify: " + _open("spotify"))
    time.sleep(4.0)  # let the web player load before sending the media key
    summary.append("Music: " + _resume_playback())
    time.sleep(1.0)

    # 3) Terminal + type "qwen"
    if player:
        player.write_log("[work_mode] opening terminal")
    term = _open("terminal")
    summary.append("Terminal: " + term)
    if "could not" not in term.lower() and "failed" not in term.lower():
        time.sleep(2.5)  # let the terminal appear and take focus
        summary.append("Terminal input: " + _type_in_terminal("qwen"))

    # 4) ChatGPT
    if player:
        player.write_log("[work_mode] opening ChatGPT")
    summary.append("ChatGPT: " + _open("chatgpt"))

    if player:
        player.write_log("[work_mode] complete")

    return "Work mode activated — " + "; ".join(summary) + "."


def work_mode_off(parameters=None, response=None, player=None, session_memory=None) -> str:
    """Turn off Work Mode — close everything it opened, best-effort."""
    from actions.computer_settings import close_app
    from actions.browser_control import browser_control

    def _close_app(app: str) -> str:
        try:
            return close_app(app)
        except Exception as e:
            return f"could not close {app}: {e}"

    def _close_tab(name: str) -> str:
        try:
            return browser_control(
                parameters={"action": "close_tab", "tab_name": name},
                player=player,
            )
        except Exception as e:
            return f"could not close {name} tab: {e}"

    summary = []

    # 1) VS Code
    if player:
        player.write_log("[work_mode_off] closing VS Code")
    summary.append("VS Code: " + _close_app("visual studio code"))

    # 2) Terminal
    if player:
        player.write_log("[work_mode_off] closing terminal")
    summary.append("Terminal: " + _close_app("terminal"))

    # 3) Spotify (browser tab)
    if player:
        player.write_log("[work_mode_off] closing Spotify tab")
    summary.append("Spotify: " + _close_tab("Spotify"))

    # 4) ChatGPT (browser tab)
    if player:
        player.write_log("[work_mode_off] closing ChatGPT tab")
    summary.append("ChatGPT: " + _close_tab("ChatGPT"))

    if player:
        player.write_log("[work_mode_off] complete")

    return "Work mode deactivated — " + "; ".join(summary) + "."
