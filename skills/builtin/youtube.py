# -*- coding: utf-8 -*-
"""YouTube skill — wraps ``actions.youtube_video``."""

from skills.base import Skill, Tool


def _handle(args, context):
    from actions.youtube_video import youtube_video
    return youtube_video(parameters=args, response=None, player=context.ui)


skill = Skill()
skill.name = "youtube"
skill.display_name = "YouTube"
skill.description = "Searches, plays, summarises and controls YouTube."
skill.permissions = ["browser", "network", "media_control"]
skill.tools = [
    Tool(
        name="youtube_video",
        description=(
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": [],
        },
        handler=_handle,
    )
]
