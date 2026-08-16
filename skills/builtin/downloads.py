# -*- coding: utf-8 -*-
"""Downloads skill — wraps ``actions.downloader``."""

from skills.base import Skill, Tool

_description = (
    "Downloads a file from a URL straight to the user's Downloads folder (or a "
    "chosen folder). Use this whenever the user asks to download, get, fetch or "
    "save a file, program, installer, image, document, or media. Pass the DIRECT "
    "file URL (ending in .exe/.msi/.zip/.pdf/etc., or any link that resolves to "
    "a file). If you only have a download page, first find the direct link with "
    "browser_control or web_search, then call this tool with that link. "
    "Set install=true to run an installer or extract an archive automatically "
    "after the download finishes. NEVER just open the browser and tell the user "
    "to download/install it themselves — actually complete the download."
)

_parameters = {
    "type": "OBJECT",
    "properties": {
        "url":       {"type": "STRING", "description": "Direct URL of the file to download."},
        "file_name": {"type": "STRING", "description": "Optional desired file name (otherwise taken from the URL/server)."},
        "folder":    {"type": "STRING", "description": "Optional destination folder (defaults to the user's Downloads folder)."},
        "install":   {"type": "BOOLEAN", "description": "Set true to run an installer or extract an archive after downloading."},
    },
    "required": ["url"],
}


def _handle(args, context):
    from actions.downloader import download_file
    return download_file(parameters=args, player=context.ui, speak=context.speak)


skill = Skill()
skill.name = "downloads"
skill.display_name = "Downloads"
skill.description = "Downloads files from the web to the user's Downloads folder, optionally installing them."
skill.permissions = ["filesystem", "network", "execution"]
skill.tools = [Tool(name="download_file", description=_description,
                    parameters=_parameters, handler=_handle)]
