# -*- coding: utf-8 -*-
"""
Permission vocabulary.

Every skill declares which capabilities it requires. The registry tracks which
permissions have been granted per skill. A skill is only allowed to run when all
of its declared permissions have been granted.

Built-in skills (which merely re-wrap functionality that already existed) are
granted their declared permissions by default so no current feature regresses.
Custom / dynamically-created skills start UNGRANTED — the manager will not run
them until the user approves their permissions.
"""

from __future__ import annotations

# permission key -> human-readable description (used for user-facing prompts/logs)
KNOWN_PERMISSIONS: dict[str, str] = {
    "browser":         "Control a web browser (navigate, click, type, tabs)",
    "filesystem":      "Read, write, move and delete files and folders",
    "network":         "Make network requests (web search, APIs)",
    "system_control":  "Control the OS (volume, brightness, WiFi, power, apps)",
    "screen":          "Capture and inspect the screen",
    "camera":          "Access the webcam",
    "messaging":       "Send messages on the user's behalf (Telegram, WhatsApp…)",
    "media_control":   "Control media playback (play / pause / next / previous)",
    "execution":       "Run arbitrary code or shell subprocesses",
    "sensitive_data":  "Access personal or sensitive user data",
}


def validate_permissions(permissions: list[str]) -> tuple[bool, list[str]]:
    """Return (all_known, unknown_list)."""
    unknown = [p for p in permissions if p not in KNOWN_PERMISSIONS]
    return (not unknown), unknown


def describe(permissions: list[str]) -> list[str]:
    return [KNOWN_PERMISSIONS.get(p, p) for p in permissions]
