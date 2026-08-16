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


def _work_mode(args, context):
    from actions.work_mode import work_mode
    return work_mode(parameters=args, player=context.ui)


def _work_mode_off(args, context):
    from actions.work_mode import work_mode_off
    return work_mode_off(parameters=args, player=context.ui)


def _game_mode(args, context):
    from actions.game_mode import game_mode
    return game_mode(parameters=args, player=context.ui)


def _game_mode_off(args, context):
    from actions.game_mode import game_mode_off
    return game_mode_off(parameters=args, player=context.ui)


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
            "restarting the PC, shutting down the PC (immediately OR on a timer), cancelling a "
            "scheduled shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command (NOT for turning the assistant itself off)."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform. Volume actions: 'volume_set' (with value=0-100), 'volume_up', 'volume_down', 'mute', 'unmute'. Others: 'brightness_up', 'brightness_down', 'close_app', 'restart', 'shutdown', 'cancel_shutdown', 'screenshot', 'type_text', 'press_key', 'dark_mode', 'toggle_wifi', 'lock_screen', 'show_desktop'. 'show_desktop' minimizes ALL open windows to reveal the desktop — use it when the user says 'show the desktop' / 'покажи рабочий стол' meaning reveal/minimize, NOT to list files. To shut down or restart AFTER a delay, use action='shutdown' or 'restart' and set delay_minutes to the number of minutes. To abort a scheduled shutdown/restart, use action='cancel_shutdown'."},
                "description": {"type": "STRING", "description": "Natural language description of what to do (used when action is empty)"},
                "value":       {"type": "STRING", "description": "Optional value. volume_set: integer 0-100. type_text: text to type. close_app: app name. press_key: key name."},
                "app_name":    {"type": "STRING", "description": "Application name to close (close_app), e.g. 'Telegram', 'Discord', 'Steam'"},
                "delay_minutes": {"type": "INTEGER", "description": "Delay in minutes before shutting down or restarting (shutdown/restart actions). Omit or 0 for immediate."},
                "confirmed":   {"type": "STRING", "description": "Set to 'yes' to confirm an IMMEDIATE shutdown or restart (required only when delay_minutes is 0 or omitted)."},
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
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task. 'list' lists the FILES and folders that are ON the desktop (does NOT minimize windows — to reveal/minimize the desktop use computer_settings action='show_desktop')."},
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
    Tool(
        name="work_mode",
        description=(
            "Activates JARVIS's 'Work Mode' (рабочий режим). Call this when the user says "
            "'work mode', 'рабочий режим', 'включи рабочий режим', 'запусти рабочий режим', "
            "or asks to set up their work environment. It opens VS Code, opens Spotify in the "
            "browser and resumes the last paused track, opens a terminal and types 'qwen', and "
            "opens ChatGPT."
        ),
        parameters={"type": "OBJECT", "properties": {}},
        handler=_work_mode,
    ),
    Tool(
        name="work_mode_off",
        description=(
            "Turns OFF JARVIS's 'Work Mode' (рабочий режим). Call this when the user says "
            "'turn off work mode', 'stop work mode', 'выключи рабочий режим', 'закрой рабочий "
            "режим', or wants to end their work environment. It closes everything Work Mode "
            "opened: VS Code, the terminal, and the Spotify + ChatGPT browser tabs."
        ),
        parameters={"type": "OBJECT", "properties": {}},
        handler=_work_mode_off,
    ),
    Tool(
        name="game_mode",
        description=(
            "Activates JARVIS's 'Game Mode' (игровой режим). Call this when the user says "
            "'game mode', 'игровой режим', 'включи игровой режим', or asks to switch to gaming. "
            "It first turns off Work Mode (closing VS Code, the terminal, and the Spotify + "
            "ChatGPT tabs), then opens Steam, Discord, and Spotify."
        ),
        parameters={"type": "OBJECT", "properties": {}},
        handler=_game_mode,
    ),
    Tool(
        name="game_mode_off",
        description=(
            "Turns OFF JARVIS's 'Game Mode' (игровой режим). Call this when the user says "
            "'turn off game mode', 'stop game mode', 'выключи игровой режим', 'закрой игровой "
            "режим', or wants to end their gaming session. It closes everything Game Mode "
            "opened: Steam, Discord, and the Spotify browser tab."
        ),
        parameters={"type": "OBJECT", "properties": {}},
        handler=_game_mode_off,
    ),
]
