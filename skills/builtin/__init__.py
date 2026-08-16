# -*- coding: utf-8 -*-
"""
Built-in skills.

Each built-in skill is a thin, self-contained wrapper over an existing
``actions/*`` function (or a small new capability) exposed through the same
``Skill`` interface as custom skills. Importing this package only *instantiates*
skill metadata — no action code runs until a tool is actually invoked.
"""

from skills.builtin import browser, coding, files, youtube, telegram, system, research, finance, media, downloads

BUILTIN_SKILLS = [
    browser.skill,
    coding.skill,
    files.skill,
    youtube.skill,
    telegram.skill,
    system.skill,
    research.skill,
    finance.skill,
    media.skill,
    downloads.skill,
]

# 'custom' is not a built-in skill — it is the reserved on-disk namespace for
# user-created skills under ``skills/custom/`` (see skills/manager.py).
