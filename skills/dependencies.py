# -*- coding: utf-8 -*-
"""
Safe dependency installation for skills.

Never uses a shell, never passes user input as a command string — every pip
invocation is a fixed argv list with ``--no-input`` so pip cannot hang waiting
for a prompt. Installation is opt-in: callers pass ``auto_install`` to install
without asking; otherwise dependencies are only reported, not installed.
"""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys


def is_importable(module_name: str) -> bool:
    """True if a top-level module/package can be imported."""
    try:
        return importlib.util.find_spec(module_name.split(".")[0]) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def missing_packages(packages: list[str]) -> list[str]:
    """Return the subset of ``packages`` that are not importable.

    Package names may differ from import names (e.g. ``PyQt6`` -> ``PyQt6``,
    ``beautifulsoup4`` -> ``bs4``); we check a few common aliases best-effort.
    """
    _ALIASES = {
        "beautifulsoup4": "bs4",
        "pillow": "PIL",
        "python-dotenv": "dotenv",
        "youtube-transcript-api": "youtube_transcript_api",
        "google-generativeai": "google.generativeai",
        "google-genai": "google.genai",
        "pycaw": "pycaw",
        "opencv-python": "cv2",
    }
    missing: list[str] = []
    for pkg in packages:
        candidate = _ALIASES.get(pkg.lower(), pkg.replace("-", "_"))
        if not is_importable(candidate):
            missing.append(pkg)
    return missing


def install(packages: list[str], auto_install: bool = False) -> tuple[bool, str]:
    """Install ``packages`` with pip.

    Returns ``(ok, message)``. When ``auto_install`` is False the packages are
    only *reported* (the caller is responsible for asking the user first).
    """
    packages = [p for p in packages if p]
    if not packages:
        return True, "no dependencies"

    to_install = missing_packages(packages)
    if not to_install:
        return True, "dependencies already satisfied"

    if not auto_install:
        return (
            False,
            "dependencies not installed (requires approval): "
            + ", ".join(to_install),
        )

    argv = [
        sys.executable, "-m", "pip", "install",
        "--no-input", "--disable-pip-version-check",
        *to_install,
    ]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=300,
            # keep creationflags off — on Windows the global Popen patch in
            # main.py already hides the console window; here we run detached-safe.
        )
    except Exception as e:  # noqa: BLE001
        return False, f"pip failed to launch: {e}"

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return False, "pip install failed: " + " | ".join(tail)

    # Re-check after install (some packages install under a different import name).
    still_missing = missing_packages(to_install)
    if still_missing:
        return (
            False,
            "installed but import check still failed for: " + ", ".join(still_missing),
        )
    return True, "installed: " + ", ".join(to_install)
