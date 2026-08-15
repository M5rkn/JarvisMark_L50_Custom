# -*- coding: utf-8 -*-
"""System skill — wraps OS control, apps, games, reminders and hardware status."""

from skills.base import Skill, Tool


def _open_app(args, context):
    from actions.open_app import open_app
    return open_app(parameters=args, response=None, player=context.ui)


def _computer_settings(args, context):
    from actions.computer_settings import computer_settings
    return computer_settings(parameters=args, response=None, player=context.ui)


def _computer_control(args, context):
    from actions.computer_control import computer_control
    return computer_control(parameters=args, player=context.ui)


def _desktop_control(args, context):
    from actions.desktop import desktop_control
    return desktop_control(parameters=args, player=context.ui)


def _game_updater(args, context):
    from actions.game_updater import game_updater
    return game_updater(parameters=args, player=context.ui, speak=context.speak)


def _reminder(args, context):
    from actions.reminder import reminder
    return reminder(parameters=args, response=None, player=context.ui)


def _system_status(args, context):
    from actions.system_monitor import get_system_status
    return str(get_system_status())


skill = Skill()
skill.name = "system"
skill.display_name = "System"
skill.description = "Controls the computer: apps, volume, power, hardware status, games, reminders."
skill.permissions = ["system_control", "execution"]
skill.tools = [
    Tool(
        name="open_app",
        description=(
            "Opens any application on the computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "app_name": {"type": "STRING", "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"}
            },
            "required": ["app_name"],
        },
        handler=_open_app,
    ),
    Tool(
        name="computer_settings",
        description=(
            "Controls the COMPUTER: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, "
            "restarting the PC, shutting down the PC, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command (NOT for turning the assistant itself off)."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform. Volume actions: 'volume_set' (with value=0-100), 'volume_up', 'volume_down', 'mute', 'unmute'. Others: 'brightness_up', 'brightness_down', 'close_app', 'restart', 'shutdown', 'screenshot', 'type_text', 'press_key', 'dark_mode', 'toggle_wifi', 'lock_screen'."},
                "description": {"type": "STRING", "description": "Natural language description of what to do (used when action is empty)"},
                "value":       {"type": "STRING", "description": "Optional value. volume_set: integer 0-100. type_text: text to type. close_app: app name. press_key: key name."},
                "app_name":    {"type": "STRING", "description": "Application name to close (close_app), e.g. 'Telegram', 'Discord', 'Steam'"},
            },
            "required": [],
        },
        handler=_computer_settings,
    ),
    Tool(
        name="computer_control",
        description="Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"],
        },
        handler=_computer_control,
    ),
    Tool(
        name="desktop_control",
        description="Controls the desktop: wallpaper, organize, clean, list, stats.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"],
        },
        handler=_desktop_control,
    ),
    Tool(
        name="game_updater",
        description=(
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use browser_control or web_search for Steam/Epic."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": [],
        },
        handler=_game_updater,
    ),
    Tool(
        name="reminder",
        description="Sets a timed reminder using Task Scheduler.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"},
            },
            "required": ["date", "time", "message"],
        },
        handler=_reminder,
    ),
    Tool(
        name="system_status",
        description=(
            "Returns real-time system metrics: CPU usage, RAM, GPU load, CPU temperature, "
            "uptime, and process count. Use when the user asks about computer performance, "
            "temperature, memory, or resource usage."
        ),
        parameters={"type": "OBJECT", "properties": {}},
        handler=_system_status,
    ),
]
