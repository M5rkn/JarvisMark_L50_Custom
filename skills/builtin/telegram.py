# -*- coding: utf-8 -*-
"""Telegram (messaging) skill — wraps ``actions.send_message``."""

from skills.base import Skill, Tool


def _handle(args, context):
    from actions.send_message import send_message
    return send_message(parameters=args, response=None, player=context.ui, session_memory=None)


skill = Skill()
skill.name = "telegram"
skill.display_name = "Messaging"
skill.description = "Sends text messages via WhatsApp, Telegram, and other platforms."
skill.permissions = ["messaging"]
skill.tools = [
    Tool(
        name="send_message",
        description="Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."},
            },
            "required": ["receiver", "message_text", "platform"],
        },
        handler=_handle,
    )
]
