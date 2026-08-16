# -*- coding: utf-8 -*-
"""
Game Mode ("Игровой режим") — switch from work to gaming.

Triggered when the user says "game mode" / "игровой режим". It first turns off
Work Mode (closing everything that mode opened), then opens Steam, Discord and
Spotify. Each step is best-effort and isolated, so one failure never aborts the
rest.
"""

import time


def game_mode(parameters=None, response=None, player=None, session_memory=None) -> str:
    from actions.work_mode import work_mode_off
    from actions.open_app import open_app

    def _open(app: str) -> str:
        try:
            return open_app(parameters={"app_name": app}, player=player)
        except Exception as e:
            return f"could not open {app}: {e}"

    summary = []

    # 1) Close whatever Work Mode opened first.
    if player:
        player.write_log("[game_mode] turning off work mode")
    summary.append("Work mode: " + work_mode_off(player=player))

    # 2) Steam
    if player:
        player.write_log("[game_mode] opening Steam")
    summary.append("Steam: " + _open("steam"))
    time.sleep(1.0)

    # 3) Discord
    if player:
        player.write_log("[game_mode] opening Discord")
    summary.append("Discord: " + _open("discord"))
    time.sleep(1.0)

    # 4) Spotify (browser tab, matching Work Mode's behaviour)
    if player:
        player.write_log("[game_mode] opening Spotify")
    summary.append("Spotify: " + _open("spotify"))

    if player:
        player.write_log("[game_mode] complete")

    return "Game mode activated — " + "; ".join(summary) + "."


def game_mode_off(parameters=None, response=None, player=None, session_memory=None) -> str:
    """Turn off Game Mode — close everything it opened, best-effort."""
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

    # 1) Steam
    if player:
        player.write_log("[game_mode_off] closing Steam")
    summary.append("Steam: " + _close_app("steam"))

    # 2) Discord
    if player:
        player.write_log("[game_mode_off] closing Discord")
    summary.append("Discord: " + _close_app("discord"))

    # 3) Spotify (browser tab, matching Game Mode's behaviour)
    if player:
        player.write_log("[game_mode_off] closing Spotify tab")
    summary.append("Spotify: " + _close_tab("Spotify"))

    if player:
        player.write_log("[game_mode_off] complete")

    return "Game mode deactivated — " + "; ".join(summary) + "."
