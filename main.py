from __future__ import annotations

import platform as _platform
import subprocess as _subprocess

# ── Nuclear: force CREATE_NO_WINDOW on EVERY subprocess call on Windows ───────
# This patches Popen itself, so no per-file flag is needed anywhere.
if _platform.system() == "Windows":
    _OrigPopen = _subprocess.Popen

    class _Popen(_OrigPopen):
        def __init__(self, args, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | _subprocess.CREATE_NO_WINDOW
            kw.pop("startupinfo", None)   # drop any stale/shared STARTUPINFO
            # Windows console commands emit OEM (cp866) text, but subprocess decodes
            # text mode with the ANSI locale (cp1251) → UnicodeDecodeError on bytes
            # like 0x98. Never crash on text reads: replace undecodable bytes.
            if (kw.get("text") or kw.get("universal_newlines")) and kw.get("errors") is None:
                kw["errors"] = "replace"
            super().__init__(args, **kw)

    _subprocess.Popen = _Popen
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import re
import threading
import time
import json
import sys
import traceback

# Prevent UnicodeEncodeError on Windows consoles using cp1251/cp866: emoji and
# other non-ASCII in print() must never crash the app. Replace unencodable chars.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

from datetime import datetime
from pathlib import Path

import sounddevice as sd
import numpy as np
from google import genai
from google.genai import types
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    save_session_summary,
    recall_memory, add_layer_memory, guess_memory_layer,
    format_layered_memory_context,
)

from actions.file_processor import file_processor
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.work_mode        import work_mode, work_mode_off
from actions.game_mode         import game_mode, game_mode_off
from actions.screen_processor  import _capture_camera, _capture_screen_with_metadata
from actions.youtube_video     import youtube_video
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater
from actions.system_monitor    import SystemMonitor, get_system_status
from actions.proactive         import ProactiveEngine
from actions.background_monitor import (
    add_monitor, remove_monitor, list_monitors, check_all as monitor_check_all,
)
from memory.config_manager     import get_brief_enabled
from skills.manager            import SkillManager
from core.context              import ContextEngine
from core.state                import DecisionLayer, classify_failure, verify_success
from core.voice import (
    IDLE, LISTENING, PROCESSING, SPEAKING, INTERRUPTED,
    BARGE_IN_ENABLED,
    EndOfSpeechDetector, BargeInDetector, DuplicateGuard,
)


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-latest"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

# Voice-pipeline tuning. (End-of-speech / barge-in / dedup thresholds now live in
# core/voice.py so the decision logic is unit-testable.)
POST_SPEECH_GRACE     = 0.5   # seconds the mic stays suppressed after TTS ends (echo tail)
SESSION_LOG_COMPACT_AT = 40   # turns before older turns are summarised away
SESSION_LOG_KEEP       = 20   # most-recent turns kept verbatim after compaction

# Only tools whose operation is read-only may be retried automatically. A
# timeout can occur after a side effect has completed, so commands that send,
# open, modify, or control anything must report the ambiguous outcome instead.
_AUTO_RETRY_READ_ONLY_TOOLS = {
    "get_current_time", "system_status", "weather_report", "web_search",
}

_KEYFILE_PATH   = BASE_DIR / "config" / ".keyfile"
_api_key_cache: str | None = None


def _get_api_key() -> str:
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache
    from core.crypto import decrypt_api_key
    data = json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
    raw  = data["gemini_api_key"]
    key  = decrypt_api_key(raw, _KEYFILE_PATH)
    # Migrate plaintext key to encrypted on first load
    if key == raw and not raw.startswith("enc:"):
        _migrate_key_to_encrypted(key)
    _api_key_cache = key
    return key


def _migrate_key_to_encrypted(key: str) -> None:
    """Re-save a plaintext API key in encrypted form (one-time migration)."""
    from core.crypto import encrypt_api_key
    try:
        data = json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
        data["gemini_api_key"] = encrypt_api_key(key, _KEYFILE_PATH)
        API_CONFIG_PATH.write_text(json.dumps(data, indent=4), encoding="utf-8")
        print("[Crypto] ✅ API key encrypted and saved.")
    except Exception as e:
        print(f"[Crypto] ⚠️ Could not migrate key: {e}")


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:    
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()

from core.tools import TOOL_DECLARATIONS, CORE_TOOL_DECLARATIONS, SKILL_MGMT_TOOL_DECLARATIONS

if False:  # unreachable — keeps linters quiet; real declarations live in core/tools.py
    TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application, website, or system settings dialog on the computer. "
            "Use this whenever the user asks to open, launch, or start any app, website, "
            "program, or settings window (e.g. 'Settings', 'Power management', 'Power "
            "options', 'Device manager', 'Network connections', 'Control panel', "
            "'Wi-Fi settings', 'Bluetooth settings'). Always call this tool — never just "
            "say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application or settings page (e.g. 'WhatsApp', 'Chrome', 'Spotify', 'power management', 'device manager', 'network connections')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": (
            "Searches the web. Use for ANY question about current facts, events, prices, "
            "or topics — always prefer this over guessing. "
            "Modes: 'search' (default), 'news' (latest headlines on a topic), "
            "'research' (deep comprehensive answer), 'price' (product cost lookup), "
            "'compare' (side-by-side comparison of items)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query or topic"},
                "mode":   {"type": "STRING", "description": "search | news | research | price | compare"},
                "items":  {"type": "ARRAY",  "items": {"type": "STRING"}, "description": "Items to compare (compare mode)"},
                "aspect": {"type": "STRING", "description": "Comparison aspect: price | specs | reviews | features"},
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_current_time",
        "description": (
            "Returns the exact current date and time right now. Use this whenever the user "
            "asks for the current time, date, or day of week, or when calculating times for "
            "reminders and schedules. Always call this instead of answering from memory."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "system_status",
        "description": (
            "Returns real-time system metrics: CPU usage, RAM, GPU load, CPU temperature, "
            "uptime, and process count. Use when the user asks about computer performance, "
            "temperature, memory, or resource usage."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures the full desktop, active window, a requested region, or webcam image and lets you analyze it. "
            "MUST be called when user asks what is on screen, what you see, "
            "look at camera, analyze my screen, read visible text/errors, identify a window, or find a visible button. "
            "You have NO visual ability without this tool. "
            "After the image is captured it is sent directly to you — describe what you see and answer the user's question. Do not claim a precise UI target when uncertain. "
            "When using camera: the live view stays open until user says close it or calls close_camera."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture the desktop, 'camera' for webcam. Default: 'screen'"},
                "target": {"type": "STRING", "description": "For screen captures: fullscreen | active_window | region. Default: fullscreen."},
                "region": {"type": "OBJECT", "description": "Required only with target=region: {x, y, width, height} in screen pixels."},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "close_camera",
        "description": (
            "Closes the live camera view shown on screen. "
            "Call when user says: close camera, stop camera, turn off camera, "
            "kamerayı kapat, kapat, creepy, etc."
        ),
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the COMPUTER: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, "
            "restarting the PC, shutting down the PC (immediately OR on a timer), cancelling a "
            "scheduled shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command (NOT for turning the assistant itself off)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform. Volume actions: 'volume_set' (with value=0-100), 'volume_up', 'volume_down', 'mute', 'unmute'. Others: 'brightness_up', 'brightness_down', 'close_app', 'restart', 'shutdown', 'cancel_shutdown', 'screenshot', 'type_text', 'press_key', 'dark_mode', 'toggle_wifi', 'lock_screen', 'show_desktop'. 'show_desktop' minimizes ALL open windows to reveal the desktop — use it when the user says 'show the desktop' / 'покажи рабочий стол' meaning reveal/minimize, NOT to list files. To shut down or restart AFTER a delay, use action='shutdown' or 'restart' and set delay_minutes to the number of minutes. To abort a scheduled shutdown/restart, use action='cancel_shutdown'."},
                "description": {"type": "STRING", "description": "Natural language description of what to do (used when action is empty)"},
                "value":       {"type": "STRING", "description": "Optional value. volume_set: integer 0-100. type_text: text to type. close_app: app name. press_key: key name."},
                "app_name":    {"type": "STRING", "description": "Application name to close (close_app), e.g. 'Telegram', 'Discord', 'Steam'"},
                "delay_minutes": {"type": "INTEGER", "description": "Delay in minutes before shutting down or restarting (shutdown/restart actions). Omit or 0 for immediate."},
                "confirmed":   {"type": "STRING", "description": "Set to 'yes' to confirm an IMMEDIATE shutdown or restart (required only when delay_minutes is 0 or omitted)."},
            },
            "required": []
        }
    },
    {
        "name": "work_mode",
        "description": (
            "Activates JARVIS's 'Work Mode' (рабочий режим). Call this when the user says "
            "'work mode', 'рабочий режим', 'включи рабочий режим', 'запусти рабочий режим', "
            "or asks to set up their work environment. It opens VS Code, opens Spotify in the "
            "browser and resumes the last paused track, opens a terminal and types 'qwen', and "
            "opens ChatGPT."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    },
    {
        "name": "work_mode_off",
        "description": (
            "Turns OFF JARVIS's 'Work Mode' (рабочий режим). Call this when the user says "
            "'turn off work mode', 'stop work mode', 'выключи рабочий режим', 'закрой рабочий "
            "режим', or wants to end their work environment. It closes everything Work Mode "
            "opened: VS Code, the terminal, and the Spotify + ChatGPT browser tabs."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    },
    {
        "name": "game_mode",
        "description": (
            "Activates JARVIS's 'Game Mode' (игровой режим). Call this when the user says "
            "'game mode', 'игровой режим', 'включи игровой режим', or asks to switch to gaming. "
            "It first turns off Work Mode (closing VS Code, the terminal, and the Spotify + "
            "ChatGPT tabs), then opens Steam, Discord, and Spotify."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    },
    {
        "name": "game_mode_off",
        "description": (
            "Turns OFF JARVIS's 'Game Mode' (игровой режим). Call this when the user says "
            "'turn off game mode', 'stop game mode', 'выключи игровой режим', 'закрой игровой "
            "режим', or wants to end their gaming session. It closes everything Game Mode "
            "opened: Steam, Discord, and the Spotify browser tab."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls any web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, screenshots, navigation, any web-based task. "
            "CLOSING: to close a SINGLE tab, ALWAYS use action='close_tab' with tab_name=<title> "
            "or index=<number> — it closes only that tab and never the browser. Use action='close' "
            "to close one ENTIRE browser, or 'close_all' to close every browser window — only when "
            "the user explicitly asks to close the browser/window itself, never for a tab. "
            "Tab management: list_tabs (show open tabs), switch_tab (switch to a tab by name/index), "
            "close_tab (close a tab by name/index), tab_history (recent tabs), close_duplicates "
            "(close duplicate tabs), protect/unprotect (protect a tab from closing), "
            "current_tab (info about the active tab), open_in_new_tab (duplicate active tab). "
            "Workspaces: action='workspace' with command=save|restore|list|delete|close and name=<name>. "
            "Control mode: action='cdp_launch' restarts Chrome with remote debugging so JARVIS can "
            "manage the real browser's tabs. "
            "Simple open/search requests launch the user's own browser normally (their real profile "
            "and logged-in accounts); interactive actions (click, type, fill_form...) attach an "
            "automation browser. "
            "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'open in Edge', "
            "'use Firefox', 'open Chrome'). Multiple browsers can run simultaneously."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all | list_tabs | switch_tab | tab_history | close_duplicates | protect | unprotect | current_tab | open_in_new_tab | workspace | cdp_launch | copy_link | scroll_to | click_first_result"},
                "browser":     {"type": "STRING", "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."},
                "tab_name":    {"type": "STRING", "description": "Tab name/title (or part of it) for switch_tab / close_tab / protect. Use only key words, e.g. 'Gmail', 'GitHub'."},
                "index":       {"type": "INTEGER", "description": "Tab number (1-based) for switch_tab / close_tab."},
                "command":     {"type": "STRING", "description": "Workspace command: save | restore | list | delete | close (workspace action)"},
                "name":        {"type": "STRING", "description": "Workspace name (workspace action)"},
                "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "engine":      {"type": "STRING", "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up | down for scroll"},
                "position":    {"type": "STRING", "description": "top | bottom for scroll_to action"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
                "path":        {"type": "STRING", "description": "Save path for screenshot"},
                "background":  {"type": "BOOLEAN", "description": "Open a new tab in the background without switching to it (new_tab action)"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: list a folder's contents (e.g. the desktop), search/find files AND folders by name, create, delete, move, copy, rename, read, write, largest files, disk usage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, pictures, music, videos, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File or folder name to search for (find action)"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf, .jpg) — files only"},
                "find_type":   {"type": "STRING", "description": "What to search: files | folders | both (default: both)"},
                "max_results": {"type": "INTEGER", "description": "Max search results (default: 20)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
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
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: LAUNCHING/opening/playing games, installing, downloading, "
            "updating games, listing installed games, checking download status, "
            "scheduling updates, and closing or restarting Steam itself. "
            "To OPEN / LAUNCH / PLAY a game (e.g. 'open PUBG', 'запусти игру'), "
            "call with action='launch' and game_name=<game>. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use browser_control, web_search, or open_app for Steam/Epic games."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "launch | update | install | list | download_status | schedule | cancel_schedule | schedule_status | close | restart (default: update). 'launch' opens/plays a game by name or app_id; 'close'/'restart' act on Steam itself"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported). Required for launch/install."},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install/launch (optional; use game_name instead when possible)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "manage_monitor",
        "description": (
            "Add, remove, or list background monitoring topics. "
            "JARVIS checks these topics once a day and alerts the user when there is a new development. "
            "Use 'add' when the user says 'monitor X', 'track X', 'follow X'. "
            "Use 'remove' when the user says 'stop monitoring X'. "
            "Use 'list' when the user asks what is being monitored. "
            "Do NOT add crypto, financial, or trading topics."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type":        "STRING",
                    "description": "add | remove | list",
                },
                "topic": {
                    "type":        "STRING",
                    "description": "Topic to monitor or stop monitoring (e.g. 'space exploration', 'AI news')",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "shutdown_jarvis",
        "description": (
            "Turns OFF / shuts down the assistant itself (Jarvis) completely — the program exits. "
            "Call this when the user wants to turn the assistant off, stop it, close it, or say goodbye "
            "(e.g. 'выключись', 'turn yourself off', 'shut down', 'stop', 'goodbye'). "
            "To restart Jarvis itself (not the computer), call restart_jarvis. "
            "NOT for restarting or shutting down the COMPUTER — those use computer_settings "
            "with action='restart' or action='shutdown'. The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "restart_jarvis",
        "description": (
            "Restarts / reboots the assistant itself (Jarvis) — the program exits and starts again fresh. "
            "Call this when the user asks Jarvis to restart itself, reboot itself, or reload "
            "(e.g. 'перезагрузись', 'перезапустись', 'restart yourself', 'reboot', 'reload'). "
            "NOT for restarting the COMPUTER — that uses computer_settings with action='restart'. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
    "name": "file_processor",
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "add_memory",
        "description": (
            "Add a fact/event to structured multi-layer memory. Call this silently "
            "whenever the user reveals something worth remembering. JARVIS decides "
            "which layer fits best (or pass 'auto' to have it inferred):\n"
            "  short_term — current active task, what is happening right now\n"
            "  long_term  — preferences, habits, recurring patterns, durable facts\n"
            "  project    — project structure, technologies, configs, errors, fixes, decisions\n"
            "  episodic   — past sessions, completed tasks, changes made, important events\n"
            "Near-duplicate entries are automatically merged (no repeats). "
            "Do NOT announce that you are saving — just call it silently."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "content":    {"type": "STRING", "description": "The fact/event to remember, one clear sentence"},
                "layer":      {"type": "STRING", "description": "short_term | long_term | project | episodic | auto (default: auto)"},
                "labels":     {"type": "ARRAY",  "items": {"type": "STRING"}, "description": "Optional tags (e.g. ['python', 'bug'])"},
                "importance": {"type": "NUMBER",  "description": "Optional importance 0.0-1.0 (default 0.5)"},
                "kind":       {"type": "STRING", "description": "Episodic kind: session | task | change | event"},
            },
            "required": ["content"]
        }
    },
    {
        "name": "recall_memory",
        "description": (
            "Search stored memories by meaning/context (not just exact keywords). "
            "Use whenever you need to recall a past fact, preference, project detail, "
            "previous error/fix, or what happened in an earlier session. "
            "Call this BEFORE guessing — it returns the most relevant memories."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "What you are trying to recall, phrased naturally"},
                "layers": {"type": "ARRAY",  "items": {"type": "STRING"}, "description": "Optional: short_term | long_term | project | episodic"},
                "top_k":  {"type": "INTEGER", "description": "Max results to return (default 5)"},
            },
            "required": ["query"]
        }
    },
]

# SKILL_MGMT_TOOL_DECLARATIONS imported from core.tools above.
# Kept as an unreachable block so history / diffs are readable.
if False:
    SKILL_MGMT_TOOL_DECLARATIONS = [
    {
        "name": "add_skill",
        "description": (
            "Adds a brand-new capability/skill to JARVIS when the requested capability "
            "does not already exist. Use this when the user asks to add, install, create, "
            "or give JARVIS a new feature or integration (e.g. 'add Spotify control', "
            "'add email support', 'can you control my smart lights?'). "
            "JARVIS generates, installs dependencies, tests and registers the skill "
            "automatically, then confirms what it can now do."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description": {"type": "STRING", "description": "What the new skill/capability should do (required)"},
                "name":        {"type": "STRING", "description": "Optional skill name (snake_case)"},
            },
            "required": ["description"],
        },
    },
    {
        "name": "list_skills",
        "description": "Lists all installed skills and whether each is enabled or disabled.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "remove_skill",
        "description": "Removes (and disables) a skill by name. Only for skills the user wants gone.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING", "description": "Skill name"}},
            "required": ["name"],
        },
    },
    {
        "name": "disable_skill",
        "description": "Disables a skill by name without deleting it.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING", "description": "Skill name"}},
            "required": ["name"],
        },
    },
    {
        "name": "enable_skill",
        "description": "Re-enables a previously disabled skill by name.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING", "description": "Skill name"}},
            "required": ["name"],
        },
    },
]

# --- Plugin system ---


class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self._asst_name     = "JARVIS"   # updated each session from config
        # Modular Skills/Plugins system. Safely optional: if it ever fails to
        # initialise, JARVIS falls back to the legacy hardcoded dispatch.
        try:
            self.skill_manager = SkillManager(
                base_dir=BASE_DIR, ui=self.ui, speak=self.speak, api_key=_get_api_key
            )
        except Exception as e:
            print(f"[Skills] ⚠️ skill system disabled: {e}")
            self.skill_manager = None
        self.session              = None
        self.audio_in_queue       = None
        self.out_queue            = None
        self._loop                = None
        self._is_speaking         = False
        self._speaking_lock       = threading.Lock()
        self._phone_active        = False   # True while phone mic is streaming; pauses PC mic
        self._pending_vision       = None    # (img_bytes, mime_type, question, angle) to inject after tool response
        self._vision_cam_active    = False   # True if camera was opened for vision → auto-close after response
        self._vision_close_pending = False   # True after vision injected; next turn_complete closes camera
        self._vision_last_time     = 0.0     # monotonic time of last screen_process call (cooldown guard)
        self._vision_busy          = False   # True while a vision capture/inject cycle is in flight
        self._interrupted          = False   # True while draining audio after user interrupt
        self.ui.on_text_command   = self._on_text_command
        self.ui.on_remote_clicked = self._make_remote_key
        self.ui.on_interrupt      = self.interrupt
        self._turn_done_event: asyncio.Event | None = None
        self._dashboard     = None
        self._briefing_sent    = False          # morning briefing fires once per process
        self._sys_monitor      = SystemMonitor()  # persistent cooldown state
        self._proactive        = ProactiveEngine()
        self._context          = ContextEngine()   # short-term working memory + references
        self._decision         = DecisionLayer()   # task state + failure recovery
        self._last_user_speech = time.monotonic()  # updated on every user utterance
        self._mic_voice_time   = 0.0               # monotonic time of last local voice detection
        self._model_activity   = 0.0               # monotonic time of last server message
        self._tool_busy        = False             # True while a tool call is executing
        self._session_log: list[str] = []          # conversation turns for end-of-session summary
        self._post_speech_until = 0.0              # monotonic time until mic re-enables after TTS (echo tail)
        self._eos = EndOfSpeechDetector()          # local end-of-speech detection
        self._barge = BargeInDetector()            # echo-resistant barge-in detection
        self._barge_active = False                 # True while a TTS utterance is being monitored
        self._dup = DuplicateGuard()               # identical tool-call suppression
        self._qfull_log_at      = 0.0              # last time we logged a full audio queue
        self._conn_backoff      = 3                # reconnect delay in seconds (exponential backoff)
        self._last_eos_time     = 0.0              # monotonic time of last EOS signal dispatched

    def _make_remote_key(self):
        """Called from Qt main thread when user presses Remote Control."""
        if self._dashboard is None:
            self.ui.write_log(
                "SYS: Dashboard unavailable. "
                "Run: pip install fastapi \"uvicorn[standard]\" cryptography"
            )
            return None
        key    = self._dashboard.new_key()
        url    = self._dashboard.get_url()
        manual = self._dashboard.get_manual_url()
        return url, key, f"{url}/auto-login?key={key}", manual

    async def _send_to_session(self, text: str) -> None:
        """Send a text turn to the live session. No-op when not connected."""
        if self.session:
            await self.session.send_client_content(
                turns={"parts": [{"text": text}]}, turn_complete=True
            )

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
            if not value:
                # Keep the mic suppressed for a short echo tail after JARVIS
                # finishes speaking, so its own TTS (and the room's reverberation)
                # is never captured and re-interpreted as a new command.
                self._post_speech_until = time.monotonic() + POST_SPEECH_GRACE
        if value:
            self.ui.set_state(SPEAKING)
        elif not self.ui.muted:
            self.ui.set_state(IDLE)

    def interrupt(self) -> None:
        """Stop JARVIS mid-speech immediately (thread-safe).

        Called from the Qt main thread (interrupt button / hotkey) and from the
        audio callback (barge-in). The real work is marshalled onto the asyncio
        loop so it never races the audio tasks or touches asyncio objects from a
        foreign thread.
        """
        loop = self._loop
        if loop and loop.is_running():
            try:
                loop.call_soon_threadsafe(self._interrupt_on_loop)
                return
            except RuntimeError:
                pass
        self._interrupt_on_loop()

    def _interrupt_on_loop(self) -> None:
        """Run on the asyncio loop: drain queued TTS audio and reopen the mic."""
        self._interrupted = True
        q = self.audio_in_queue
        if q:
            drained = 0
            while True:
                try:
                    q.get_nowait()
                    drained += 1
                except asyncio.QueueEmpty:
                    break
            if drained:
                print(f"[JARVIS] ✋ Interrupted — {drained} audio chunks discarded")
        self.set_speaking(False)
        # Open the mic immediately: TTS is stopped, so there is no echo tail to
        # suppress. (Must run AFTER set_speaking(False), which re-applies the
        # normal POST_SPEECH_GRACE; that grace would otherwise drop the first
        # ~0.5s of the user's follow-up speech.)
        self._post_speech_until = 0.0
        if self._turn_done_event:
            self._turn_done_event.clear()
        self.ui.set_state(INTERRUPTED)
        self.ui.write_log("SYS: Interrupted — listening...")
        try:
            loop = asyncio.get_event_loop()
            loop.call_later(1.0, self._settle_interrupted)
        except RuntimeError:
            pass

    def _settle_interrupted(self) -> None:
        """Return the HUD to IDLE/LISTENING shortly after an interrupt."""
        if self.ui.muted or self._is_speaking:
            return
        now = time.monotonic()
        if self._eos.active and (now - self._eos.last_speech) < 0.5:
            self.ui.set_state(LISTENING)
        else:
            self.ui.set_state(IDLE)

    def _reset_vad(self) -> None:
        """Reset the end-of-speech detector (used while audio is suppressed)."""
        self._eos.reset()

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        # Log only. The error text is already returned in the FunctionResponse,
        # which the model phrases and speaks naturally — speaking it here too
        # caused every failure to be announced twice.
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")

    def _finish_command(self, name: str, args: dict, result: str, ok: bool = True) -> str:
        """Record a finished tool execution and apply the decision layer.

        On failure, appends a recovery hint (retry / alternative / report) so the
        model can react honestly instead of hallucinating success.
        """
        # Verification gate: never mark a result as success if it reads like a
        # failure (covers tools that return an error string without raising).
        if ok and not verify_success(result):
            ok = False
        result = self._context.complete_command(name, args, result, ok)
        hint = self._decision.finish(ok, result if not ok else None)
        if not ok and hint:
            result = f"{result}\n{hint}"
        return result

    async def _run_with_retry(self, name: str, args: dict, runner) -> tuple[bool, str]:
        """Run a blocking tool handler, retrying once on a retryable failure.

        ``runner`` is ``callable(args) -> str`` and may raise. Returns (ok, result).
        A single automatic retry is allowed only for retryable failures from an
        explicit allowlist of read-only tools. This prevents a timeout from
        repeating a command whose side effect may already have completed.
        """
        ok = True
        try:
            result = await asyncio.to_thread(runner, args)
            ok = verify_success(result)
        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            ok = False
        if (
            not ok
            and name in _AUTO_RETRY_READ_ONLY_TOOLS
            and classify_failure(result) == "retryable"
        ):
            ok = True
            try:
                result = await asyncio.to_thread(runner, args)
                ok = verify_success(result)
            except Exception as e:
                result = f"Tool '{name}' failed: {e}"
                ok = False
        return ok, result

    def _core_tool_handlers(self) -> dict:
        """Blocking core-tool handlers: name → callable(args) -> str."""
        handlers = getattr(self, "_core_handlers_cache", None)
        if handlers is not None:
            return handlers
        ui, speak = self.ui, self.speak
        handlers = {
            "open_app":          lambda a: open_app(parameters=a, response=None, player=ui) or f"Opened {a.get('app_name')}",
            "weather_report":    lambda a: weather_action(parameters=a, player=ui) or "Weather delivered.",
            "browser_control":   lambda a: browser_control(parameters=a, player=ui) or "Done.",
            "file_controller":   lambda a: file_controller(parameters=a, player=ui) or "Done.",
            "send_message":      lambda a: send_message(parameters=a, response=None, player=ui, session_memory=None) or f"Message sent to {a.get('receiver')}",
            "reminder":          lambda a: reminder(parameters=a, response=None, player=ui) or "Reminder set.",
            "youtube_video":     lambda a: youtube_video(parameters=a, response=None, player=ui) or "Done.",
            "computer_settings": lambda a: computer_settings(parameters=a, response=None, player=ui) or "Done.",
            "work_mode":         lambda a: work_mode(parameters=a, player=ui) or "Work mode activated.",
            "work_mode_off":     lambda a: work_mode_off(parameters=a, player=ui) or "Work mode deactivated.",
            "game_mode":         lambda a: game_mode(parameters=a, player=ui) or "Game mode activated.",
            "game_mode_off":     lambda a: game_mode_off(parameters=a, player=ui) or "Game mode deactivated.",
            "desktop_control":   lambda a: desktop_control(parameters=a, player=ui) or "Done.",
            "code_helper":       lambda a: code_helper(parameters=a, player=ui, speak=speak) or "Done.",
            "dev_agent":         lambda a: dev_agent(parameters=a, player=ui, speak=speak) or "Done.",
            "web_search":        lambda a: web_search_action(parameters=a, player=ui) or "Done.",
            "file_processor":    lambda a: file_processor(parameters=a, player=ui, speak=speak) or "Done.",
            "computer_control":  lambda a: computer_control(parameters=a, player=ui) or "Done.",
            "game_updater":      lambda a: game_updater(parameters=a, player=ui, speak=speak) or "Done.",
            "flight_finder":     lambda a: flight_finder(parameters=a, player=ui) or "Done.",
            "system_status":     lambda a: str(get_system_status()),
            "get_current_time":  lambda a: datetime.now().strftime("%A, %B %d, %Y — %I:%M %p"),
        }
        self._core_handlers_cache = handlers
        return handlers

    def _mirror_web_search(self, args: dict, result: str) -> None:
        """Mirror web-search results to the on-screen content panel."""
        if not result or str(result).startswith("No results") or str(result).startswith("Search failed"):
            return
        _mode = args.get("mode", "search")
        _query = args.get("query") or ", ".join(args.get("items", []))
        _label = f"{_mode.upper()} — {_query[:38]}" if _query else _mode.upper()
        self.ui.show_content(_label, str(result))

    async def _queue_visual_verification(self, args: dict, result: str) -> None:
        """Capture once after a consequential UI action for model-side verification.

        This is deliberately event-driven: no capture is made for ordinary tools,
        and the frame remains in memory only until the next Live turn receives it.
        """
        action = (args.get("action") or "").lower().strip()
        important = {"click", "double_click", "right_click", "screen_click", "type", "smart_type", "press", "hotkey", "focus_window"}
        if action not in important or self._vision_busy or self._pending_vision:
            return
        self._vision_busy = True
        try:
            image_bytes, mime_type, metadata = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _capture_screen_with_metadata("active_window")
            )
        except Exception as e:
            self._vision_busy = False
            print(f"[Vision] verification capture skipped: {e}")
            return
        question = (
            f"[VISUAL VERIFICATION] The assistant just performed computer_control action={action!r}. "
            "Inspect this fresh, transient screenshot and determine whether the intended visible change occurred. "
            "If it is unclear, say so and do not issue another click or action. "
            f"Tool reported: {str(result)[:300]}\n\n[LOCAL VISION METADATA]\n{metadata}"
        )
        self._pending_vision = (image_bytes, mime_type, question, "verification")

    async def _run_inline_tool(self, name: str, args: dict) -> tuple[bool, str]:
        """Handle the core tools that are not a single blocking call (vision,
        lifecycle, skill management, monitor, unknown)."""
        ok = True
        result = "Done."
        loop = asyncio.get_event_loop()
        try:
            if name == "screen_process":
                import time as _t_mod
                _now = _t_mod.monotonic()
                _cooldown = 4.0  # seconds — covers echo window after speaking ends
                if self._vision_busy or (_now - self._vision_last_time) < _cooldown:
                    _wait = max(0, _cooldown - (_now - self._vision_last_time))
                    print(f"[Vision] ⏳ Cooldown active ({_wait:.1f}s remaining) — ignoring duplicate call")
                    result = "Vision is still processing the previous request. I will not call this again."
                else:
                    self._vision_busy      = True
                    self._vision_last_time = _now
                    angle     = args.get("angle", "screen").lower()
                    user_text = args.get("text", "What do you see?")
                    if angle == "camera":
                        img_b, mime_t = await loop.run_in_executor(None, _capture_camera)
                        self.ui.start_camera_stream()
                        self._vision_cam_active = True
                        print(f"[Vision] 📷 Camera: {len(img_b):,} bytes")
                        _stall = "camera"
                    else:
                        target = str(args.get("target", "fullscreen")).lower()
                        region = args.get("region") if target == "region" else None
                        img_b, mime_t, metadata = await loop.run_in_executor(
                            None, lambda: _capture_screen_with_metadata(target, region)
                        )
                        print(f"[Vision] 🖥️  {target}: {len(img_b):,} bytes")
                        user_text = f"{user_text}\n\n[LOCAL VISION METADATA]\n{metadata}"
                        _stall = target.replace("_", " ")
                    self._pending_vision = (img_b, mime_t, user_text, angle)
                    result = (
                        f"[VISION_ACTIVE] {_stall.capitalize()} captured. "
                        f"Immediately say ONE short natural sentence in the user's own language, "
                        f"telling them you are looking at their {_stall} right now. "
                        f"Do NOT describe or guess content — the actual image arrives in the NEXT message."
                    )

            elif name == "close_camera":
                self.ui.stop_camera_stream()
                result = "Camera closed."

            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                async def _do_shutdown():
                    try:
                        await asyncio.wait_for(self._save_session_summary(), timeout=5.0)
                    except Exception:
                        pass
                    if self.session:
                        try:
                            await self._send_to_session("Say a brief natural goodbye to the user.")
                        except Exception:
                            pass
                    await asyncio.sleep(1.5)
                    import os as _os
                    _os._exit(0)
                asyncio.create_task(_do_shutdown())

            elif name == "restart_jarvis":
                self.ui.write_log("SYS: Restart requested.")
                async def _do_restart():
                    try:
                        await asyncio.wait_for(self._save_session_summary(), timeout=5.0)
                    except Exception:
                        pass
                    if self.session:
                        try:
                            if self._turn_done_event:
                                self._turn_done_event.clear()
                            await self._send_to_session("Say a brief natural line that you are restarting now.")
                        except Exception:
                            pass
                        try:
                            if self._turn_done_event:
                                await asyncio.wait_for(self._turn_done_event.wait(), timeout=5.0)
                            _deadline = time.monotonic() + 5.0
                            while time.monotonic() < _deadline:
                                with self._speaking_lock:
                                    speaking = self._is_speaking
                                if not speaking:
                                    break
                                await asyncio.sleep(0.05)
                        except Exception:
                            pass
                    import os as _os
                    if getattr(sys, "frozen", False):
                        args = [sys.executable, *sys.argv[1:]]
                    else:
                        args = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
                    try:
                        _os.execv(sys.executable, args)
                    except Exception:
                        _os._exit(1)
                asyncio.create_task(_do_restart())

            elif name == "add_skill":
                result = await loop.run_in_executor(
                    None,
                    lambda: self.skill_manager.create_skill(
                        description=args.get("description", ""),
                        name=args.get("name"),
                        auto_approve=True,
                        auto_install=True,
                    ),
                )

            elif name == "list_skills":
                result = self.skill_manager.list_skills()

            elif name == "remove_skill":
                result = await loop.run_in_executor(
                    None, lambda: self.skill_manager.remove_skill(args.get("name", ""))
                )

            elif name == "disable_skill":
                result = await loop.run_in_executor(
                    None, lambda: self.skill_manager.disable_skill(args.get("name", ""))
                )

            elif name == "enable_skill":
                result = await loop.run_in_executor(
                    None, lambda: self.skill_manager.enable_skill(args.get("name", ""))
                )

            elif name == "manage_monitor":
                action = args.get("action", "").lower().strip()
                topic  = args.get("topic", "").strip()
                if action == "add" and topic:
                    result = await asyncio.to_thread(add_monitor, topic)
                elif action == "remove" and topic:
                    result = await asyncio.to_thread(remove_monitor, topic)
                elif action == "list":
                    topics = await asyncio.to_thread(list_monitors)
                    result = ("Monitoring: " + ", ".join(topics)) if topics else "No topics are being monitored."
                else:
                    result = "Specify action (add/remove/list) and a topic."

            else:
                result = f"Unknown tool: {name}"
                ok = False
        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            ok = False
            if name == "screen_process":
                self._vision_busy = False
                self._pending_vision = None
            traceback.print_exc()
            self.speak_error(name, e)
        return ok, result

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        # Load customization from config
        try:
            _cfg = json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
            self._asst_name = (_cfg.get("assistant_name") or "JARVIS").strip()
            _user_name = (_cfg.get("user_name") or "").strip()
        except Exception:
            self._asst_name = "JARVIS"
            _user_name = ""

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        # Structured multi-layer context (short-term / long-term / project /
        # episodic). Kept compact and appended only when non-empty.
        layered_str = ""
        try:
            layered_str = format_layered_memory_context()
        except Exception as e:
            print(f"[Memory] ⚠️ layered context failed: {e}")

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[SESSION START TIME]\n"
            f"The session started at: {time_str}\n"
            f"For the CURRENT time or date, always call get_current_time — never rely on this value.\n\n"
        )

        # Identity injection — overrides any hardcoded name in prompt.txt
        _addr = (f"ADDRESS: Address the user as 'Sir' / 'Сэр' (match the language you speak) — "
                 f"calm and respectful, like JARVIS addressing Mr. Stark. "
                 f"Occasionally use their name '{_user_name}'. "
                 f"The user's name is exactly '{_user_name}' — NEVER invent, guess, or substitute "
                 f"any other name for them. Never use 'efendim'."
                 if _user_name
                 else "ADDRESS: Address the user as 'Sir' / 'Сэр' (match the language you speak) — "
                      "calm and respectful, like JARVIS addressing Mr. Stark. "
                      "NEVER invent or guess a name for the user. Never use 'efendim'.")
        identity_ctx = (
            f"[IDENTITY]\n"
            f"Your name is {self._asst_name}. "
            f"Always refer to yourself as {self._asst_name}.\n"
            f"{_addr}\n\n"
        )

        # Recent conversation context: carry the last few turns into the system
        # prompt so a reconnect (or a fresh Gemini Live session) does not lose
        # the immediate thread — e.g. what a pronoun like "it" / "her" refers to.
        recent_ctx = ""
        try:
            recent_turns = list(getattr(self, "_session_log", [])[-8:])
        except Exception:
            recent_turns = []
        if recent_turns:
            recent_ctx = (
                "[RECENT CONVERSATION — the last few turns, kept so an interrupted "
                "session can pick up where it left off. Use this only as context for "
                "resolving pronouns and references; do not re-answer or recite it.]\n"
                + "\n".join(f"  {t}" for t in recent_turns)
                + "\n\n"
            )

        active_ctx = ""
        try:
            active_ctx = self._context.build_context_block()
        except Exception as e:
            print(f"[Context] ⚠️ active context failed: {e}")

        # Explicit language lock — injected before the main prompt so the model
        # never defaults to English or produces bilingual replies.  Falls back to
        # Russian when language has not been detected yet (typical for first run).
        _lang_entry = memory.get("identity", {}).get("language", {})
        _lang = (
            (_lang_entry.get("value", "") if isinstance(_lang_entry, dict) else str(_lang_entry)).strip()
            or "Russian"
        )
        lang_ctx = (
            f"[ACTIVE LANGUAGE — HIGHEST PRIORITY RULE]\n"
            f"You MUST reply in {_lang} and ONLY {_lang}.\n"
            f"NEVER mix languages. NEVER translate your reply into another language.\n"
            f"NEVER produce a bilingual response. Every single word must be {_lang}.\n\n"
        )

        parts = [time_ctx, lang_ctx, identity_ctx]
        if recent_ctx:
            parts.append(recent_ctx)
        if active_ctx:
            parts.append(active_ctx)
        if mem_str:
            parts.append(mem_str)
        if layered_str:
            parts.append(layered_str)
        parts.append(sys_prompt)

        # Build the Gemini tool list dynamically: core tools + skill-management
        # tools + every ENABLED skill's tools. Disabled/broken skills are omitted,
        # so they are simply not offered to the model.
        if self.skill_manager:
            declarations = (
                CORE_TOOL_DECLARATIONS
                + SKILL_MGMT_TOOL_DECLARATIONS
                + self.skill_manager.tool_declarations()
            )
        else:
            declarations = TOOL_DECLARATIONS   # fallback: legacy behaviour

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": declarations}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Schedar"
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        # ── Duplicate-command guard ─────────────────────────────────────────
        # If the exact same tool call arrives again within a short window and no
        # new user speech happened in between, it is an echo/duplicate (e.g.
        # JARVIS hearing its own TTS) — suppress it instead of executing twice.
        try:
            sig = (name, json.dumps(args, sort_keys=True, default=str))
        except Exception:
            sig = (name, repr(args))
        if self._dup.should_suppress(sig, time.monotonic(), self._last_user_speech):
            print(f"[JARVIS] ⏭️ Duplicate suppressed: {name} {args}")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "duplicate_suppressed"},
            )

        print(f"[JARVIS] 🔧 {name}  {args}")
        self.ui.set_state(PROCESSING)
        if name not in ("save_memory", "add_memory", "recall_memory"):
            self.ui.write_log(f"SYS: Executing {name}")

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state(IDLE)
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        if name == "add_memory":
            content = (args.get("content") or "").strip()
            if content:
                layer = (args.get("layer") or "auto").strip()
                if layer not in ("short_term", "long_term", "project", "episodic"):
                    layer = guess_memory_layer(content)
                labels = list(args.get("labels") or [])
                try:
                    importance = float(args.get("importance", 0.5))
                except (TypeError, ValueError):
                    importance = 0.5
                try:
                    add_layer_memory(
                        content, layer=layer, labels=labels,
                        importance=importance, source="auto",
                        kind=args.get("kind"),
                    )
                except Exception as e:
                    print(f"[Memory] ⚠️ add_memory failed: {e}")
                print(f"[Memory] 🧠 add_memory ({layer}): {content[:60]}")
            if not self.ui.muted:
                self.ui.set_state(IDLE)
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        if name == "recall_memory":
            query  = (args.get("query") or "").strip()
            layers = args.get("layers")
            try:
                top_k = int(args.get("top_k") or 5)
            except (TypeError, ValueError):
                top_k = 5
            result = "No relevant memories found."
            if query:
                try:
                    result = await asyncio.to_thread(recall_memory, query, layers, top_k)
                except Exception as e:
                    result = f"Memory recall failed: {e}"
                    print(f"[Memory] ⚠️ recall_memory: {e}")
            if not self.ui.muted:
                self.ui.set_state(IDLE)
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": result}
            )

        # ── Decision layer: record intent and enter EXECUTING ────────────────
        self._decision.start(name, args)

        # ── Modular skill routing ─────────────────────────────────────────────
        # If a skill owns this tool name, delegate to the SkillManager. Disabled
        # or broken skills raise here (and are auto-quarantined after repeated
        # failures) instead of silently falling through to legacy handling.
        if self.skill_manager and self.skill_manager.handles(name):
            ok, result = await self._run_with_retry(
                name, args, lambda a: self.skill_manager.run(name, a)
            )
            if not self.ui.muted:
                self.ui.set_state(IDLE)
            print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")
            result = self._finish_command(name, args, result, ok)
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": result}
            )

        # ── Core tool dispatch (dict lookup, retried once on retryable failure) ──
        if name == "file_processor" and not args.get("file_path") and self.ui.current_file:
            args["file_path"] = self.ui.current_file

        handler = self._core_tool_handlers().get(name)
        if handler is not None:
            ok, result = await self._run_with_retry(name, args, handler)
            if ok and name == "web_search":
                self._mirror_web_search(args, result)
            if ok and name == "computer_control":
                await self._queue_visual_verification(args, result)
        else:
            ok, result = await self._run_inline_tool(name, args)

        if not self.ui.muted:
            self.ui.set_state(IDLE)

        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")
        result = self._finish_command(name, args, result, ok)
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            if isinstance(msg, dict) and msg.get("__eos__"):
                # Local VAD detected the end of the user's utterance — tell the
                # model so it finalises the turn immediately instead of waiting
                # for its own (slower) activity detection.
                await self.session.send_realtime_input(audio_stream_end=True)
                continue
            await self.session.send_realtime_input(audio=msg)

    def _push_audio(self, data: bytes):
        """Queue a mic chunk for sending without ever crashing the callback."""
        try:
            self.out_queue.put_nowait({"data": data, "mime_type": "audio/pcm;rate=16000"})
        except asyncio.QueueFull:
            now = time.monotonic()
            if now - self._qfull_log_at > 5.0:
                self._qfull_log_at = now
                print("[JARVIS] ⚠️ Audio send queue full — dropping a mic chunk")

    def _signal_end_of_speech(self):
        self._last_eos_time = time.monotonic()
        try:
            self.out_queue.put_nowait({"__eos__": True})
        except asyncio.QueueFull:
            pass

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
                post_speech_until = self._post_speech_until
            now = time.monotonic()

            # RMS is always computed (it is cheap) so we can run barge-in while
            # speaking below, even though that audio is never streamed to Gemini.
            rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))

            # ── Barge-in ────────────────────────────────────────────────────
            # While JARVIS is speaking, keep monitoring the mic locally so the
            # user can interrupt TTS by talking over it. This audio is NOT sent
            # to Gemini (echo suppression stays intact) — it is only used to
            # decide when to stop playback and reopen the mic. The barge-in
            # detector is owned by this callback thread (reset on the False→True
            # speaking edge here), so it never races the asyncio loop.
            if jarvis_speaking:
                if not self._barge_active:
                    self._barge_active = True
                    self._barge.reset()   # fresh echo baseline per utterance
                if BARGE_IN_ENABLED and self._barge.process(rms, now):
                    loop.call_soon_threadsafe(self._interrupt_on_loop)
                self._reset_vad()
                return

            self._barge_active = False

            # Suppress during the post-speech echo tail, while muted, or while
            # the phone mic is active. Reset the VAD so a fresh utterance always
            # starts from a clean state.
            if now < post_speech_until or self.ui.muted or self._phone_active:
                self._reset_vad()
                return

            # Local voice-activity detection: marks real mic speech so the
            # watchdog can tell "model is deaf" apart from "user is silent",
            # and lets us signal end-of-speech to the model promptly.
            if rms > self._eos.threshold:
                self._mic_voice_time = now

            event = self._eos.update(rms, now)
            if event == "onset":
                # Restart the watchdog's stall clock at the beginning of a new
                # utterance. After a long idle period _model_activity is stale
                # (last server message from long ago), so without this the
                # watchdog would force a reconnect ~5s after the user speaks
                # instead of giving the model its full 30s window.
                self._model_activity = now
                self.ui.set_state(LISTENING)

            # Push audio BEFORE the EOS marker so the model always receives the
            # last audio frame before audio_stream_end=True.  The original order
            # (EOS then audio) caused Gemini to reset its VAD and keep waiting
            # for more input, leaving JARVIS stuck in PROCESSING.
            data = indata.tobytes()
            loop.call_soon_threadsafe(self._push_audio, data)

            if event == "eos":
                # The user finished speaking — prompt the model to respond now.
                loop.call_soon_threadsafe(self._signal_end_of_speech)
                self.ui.set_state(PROCESSING)

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                print("[JARVIS] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[JARVIS] ❌ Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():
                    self._model_activity = time.monotonic()

                    if response.data:
                        if self._interrupted:
                            pass  # discard: interrupted
                        else:
                            # Mark speaking as soon as audio arrives (before it is
                            # actually played) so the mic is suppressed for the full
                            # playback window and JARVIS can't hear its own TTS.
                            with self._speaking_lock:
                                already_speaking = self._is_speaking
                            if not already_speaking:
                                self.set_speaking(True)
                            if self._turn_done_event and self._turn_done_event.is_set():
                                self._turn_done_event.clear()
                            # Split into ~50 ms chunks so interrupt() stops audio within 50 ms
                            # (24000 Hz × 2 bytes/sample × 0.05 s = 2400 bytes per slice)
                            _audio_data = response.data
                            _SLICE = 2400
                            for _i in range(0, len(_audio_data), _SLICE):
                                try:
                                    self.audio_in_queue.put_nowait(_audio_data[_i : _i + _SLICE])
                                except asyncio.QueueFull:
                                    pass  # drop chunk under playback lag rather than blocking

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt and txt != (out_buf[-1] if out_buf else ""):
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt and txt != (in_buf[-1] if in_buf else ""):
                                # Gemini streams cumulative full transcripts for the
                                # current turn. Replace instead of stacking when the
                                # new text extends the previous one, so the log and
                                # session summary never show duplicated words.
                                if in_buf and (in_buf[-1] in txt):
                                    in_buf[-1] = txt
                                else:
                                    in_buf.append(txt)
                                self._last_user_speech = time.monotonic()

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            # If this turn_complete ends an interrupted response, clear the
                            # flag and skip all further processing for that turn.
                            if self._interrupted:
                                self._interrupted = False
                                in_buf  = []
                                out_buf = []
                                continue

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                                self._session_log.append(f"User: {full_in}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "user",
                                        "text": full_in,
                                        "ts": datetime.now().isoformat(),
                                    }))
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"{self._asst_name}: {full_out}")
                                self._session_log.append(f"{self._asst_name}: {full_out}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "jarvis",
                                        "text": full_out,
                                        "ts": datetime.now().isoformat(),
                                    }))
                            out_buf = []

                            # Compact older turns so the session log stays bounded.
                            self._maybe_compact_session_log()

                            # Vision injection: model finished tool-response turn → now send the image
                            if self._pending_vision and self.session:
                                import base64 as _b64
                                img_b, mime_t, question, angle = self._pending_vision
                                self._pending_vision = None
                                b64 = _b64.b64encode(img_b).decode("ascii")
                                print(f"[Vision] 📤 {len(img_b):,} bytes (angle={angle}) → main session")
                                await self.session.send_client_content(
                                    turns={"parts": [
                                        {"inline_data": {"mime_type": mime_t, "data": b64}},
                                        {"text": question},
                                    ]},
                                    turn_complete=True,
                                )
                                # Mark next turn_complete behaviour depending on angle
                                if self._vision_cam_active:
                                    # Camera: keep busy until JARVIS finishes speaking the answer
                                    self._vision_cam_active    = False
                                    self._vision_close_pending = True
                                else:
                                    # Screen-only: no camera to close; release busy flag now
                                    self._vision_busy = False
                            elif self._vision_close_pending:
                                # This turn_complete IS the vision answer — close camera + release busy flag
                                self._vision_close_pending = False
                                self._vision_busy = False
                                async def _cam_close():
                                    await asyncio.sleep(2.0)
                                    self.ui.stop_camera_stream()
                                asyncio.create_task(_cam_close())

                    if response.tool_call:
                        self._tool_busy = True
                        try:
                            fn_responses = []
                            for fc in response.tool_call.function_calls:
                                print(f"[JARVIS] 📞 {fc.name}")
                                try:
                                    fr = await asyncio.wait_for(
                                        self._execute_tool(fc), timeout=60.0
                                    )
                                except asyncio.TimeoutError:
                                    print(f"[JARVIS] ⚠️ Tool '{fc.name}' timed out after 60s")
                                    fr = types.FunctionResponse(
                                        id=fc.id, name=fc.name,
                                        response={"result": f"Tool '{fc.name}' timed out after 60 seconds."}
                                    )
                                fn_responses.append(fr)
                            await self.session.send_tool_response(
                                function_responses=fn_responses
                            )
                        finally:
                            self._tool_busy = False
        except Exception as e:
            print(f"[JARVIS] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")

        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue

                self.set_speaking(True)

                # Batch all immediately-available chunks into one write to reduce
                # thread-pool round-trips (was one asyncio.to_thread per 50ms slice).
                # Cap at ~100 ms so interrupt() still stops audio within ~100 ms.
                batch = bytearray(chunk)
                while len(batch) < 4800:   # 4800 bytes ≈ 100 ms at 24 kHz / 16-bit mono
                    try:
                        batch.extend(self.audio_in_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                vol = self.ui.voice_volume
                if vol < 1.0:
                    arr = np.frombuffer(batch, dtype=np.int16).astype(np.float32)
                    arr *= vol
                    np.clip(arr, -32768.0, 32767.0, out=arr)
                    data = arr.astype(np.int16).tobytes()
                else:
                    data = bytes(batch)

                try:
                    await asyncio.to_thread(stream.write, data)
                except (RuntimeError, asyncio.CancelledError):
                    break   # executor shutting down — exit cleanly
        except Exception as e:
            print(f"[JARVIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    # ── Morning briefing ────────────────────────────────────────────────────────

    async def _send_startup_briefing(self) -> None:
        """Instant startup greeting: greets the user and announces the time."""
        memory   = load_memory()
        identity = memory.get("identity", {})

        def _val(k: str) -> str:
            e = identity.get(k, {})
            return (e.get("value", "") if isinstance(e, dict) else str(e)).strip()

        lang = _val("language")
        name = _val("name")
        time_str = datetime.now().strftime("%H:%M")

        await asyncio.sleep(0.3)
        if not self.session:
            return

        # Default to Russian when language is not yet detected, since that is
        # the user's language.  Never leave lang_clause empty — an empty clause
        # causes the model to fall back to English and then produce a bilingual
        # reply when it later detects Russian from the user's voice.
        active_lang = lang or "Russian"
        name_clause = f" Address the user as {name}." if name else ""

        p1 = (
            f"Greet the user warmly and mention it is {time_str}. "
            f"Ask how you can help. "
            f"Keep it to 2-3 short sentences max. Do not call any tools. "
            f"IMPORTANT: your ENTIRE reply must be in {active_lang} only — "
            f"not a single word in any other language.{name_clause}"
        )

        if self._turn_done_event:
            self._turn_done_event.clear()

        await self._send_to_session(p1)
        self.ui.write_log("SYS: Startup greeting sent.")

    # ── Session memory ──────────────────────────────────────────────────────────

    async def _save_session_summary(self) -> None:
        """Summarise the current session in 1-2 sentences and save to episodic memory."""
        log = self._session_log
        if len(log) < 3:          # need at least one exchange to be worth saving
            return
        self._session_log = []    # reset immediately so the next session starts clean

        memory = load_memory()
        lang_entry = memory.get("identity", {}).get("language", {})
        lang = (lang_entry.get("value", "") if isinstance(lang_entry, dict) else str(lang_entry)).strip()
        lang = lang or "English"

        convo = "\n".join(log[-40:])   # cap at last 40 turns to stay within token budget
        prompt = (
            f"Summarize this conversation in 1-2 sentences in {lang}. "
            "Focus on what the user accomplished or discussed. "
            "Output ONLY the summary text, nothing else:\n\n" + convo
        )
        try:
            from google import genai as _genai
            client = _genai.Client(api_key=_get_api_key())
            resp   = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.0-flash",
                contents=prompt,
            )
            summary = (resp.text or "").strip()
            if summary:
                save_session_summary(summary, lang)
        except Exception as e:
            print(f"[Memory] ⚠️ Session summary failed: {e}")

    # ── Context compression ────────────────────────────────────────────────────

    def _maybe_compact_session_log(self) -> None:
        """Keep the in-memory session log bounded by summarising older turns."""
        if len(self._session_log) <= SESSION_LOG_COMPACT_AT:
            return
        old = self._session_log[: -SESSION_LOG_KEEP]
        self._session_log = self._session_log[-SESSION_LOG_KEEP:]
        asyncio.create_task(self._compact_turns(old))
        self._session_log = self._session_log[-300:]  # hard cap: prevents unbounded growth if compaction fails silently

    async def _compact_turns(self, old_turns: list[str]) -> None:
        """Summarise older turns into short-term memory (fire-and-forget)."""
        if not old_turns:
            return
        memory = load_memory()
        lang_entry = memory.get("identity", {}).get("language", {})
        lang = (lang_entry.get("value", "") if isinstance(lang_entry, dict) else str(lang_entry)).strip() or "English"
        convo = "\n".join(old_turns[-40:])
        prompt = (
            f"Summarize this earlier part of the conversation in 1-2 sentences in {lang}. "
            "Preserve any durable facts, preferences, decisions, errors, or tasks that "
            "still matter. Output ONLY the summary text:\n\n" + convo
        )
        try:
            from google import genai as _genai
            client = _genai.Client(api_key=_get_api_key())
            resp = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.0-flash",
                contents=prompt,
            )
            summary = (resp.text or "").strip()
            if summary:
                self._context.remember(
                    summary, default_layer="short_term",
                    labels=["conversation_summary"],
                )
        except Exception as e:
            print(f"[Context] ⚠️ compaction failed: {e}")

    # ── System monitor ──────────────────────────────────────────────────────────

    async def _run_system_monitor(self) -> None:
        """Background task: voice alerts when metrics exceed thresholds."""
        while True:
            await asyncio.sleep(10)
            alert = await asyncio.to_thread(self._sys_monitor.check)
            if not alert or not self.session:
                continue
            # Don't interrupt an active conversation
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking or (time.monotonic() - self._last_user_speech) < 10:
                continue
            try:
                await self._send_to_session(alert)
            except Exception as e:
                print(f"[Monitor] ⚠️ Could not send alert: {e}")

    # ── Background monitor ──────────────────────────────────────────────────────

    async def _run_background_monitor(self) -> None:
        """Check user-configured topics once per day; speak alerts when new headlines appear."""
        await asyncio.sleep(300)          # wait 5 min after startup before first check
        while True:
            if self.session:
                # Don't interrupt if user spoke recently or JARVIS is mid-sentence
                with self._speaking_lock:
                    speaking = self._is_speaking
                recent_speech = (time.monotonic() - self._last_user_speech) < 30
                if not speaking and not recent_speech:
                    try:
                        alerts = await asyncio.to_thread(monitor_check_all)
                        memory = load_memory()
                        lang_e = memory.get("identity", {}).get("language", {})
                        lang   = (lang_e.get("value", "") if isinstance(lang_e, dict) else str(lang_e)).strip() or "English"
                        for alert in alerts:
                            msg = (
                                f"{alert}\n\n"
                                f"Inform the user about this development naturally in {lang}. "
                                "One brief sentence only."
                            )
                            await self._send_to_session(msg)
                            self.ui.write_log(f"SYS: Monitor alert sent.")
                            await asyncio.sleep(6)   # gap between consecutive alerts
                    except Exception as e:
                        print(f"[Monitor] ⚠️ Background check error: {e}")
            await asyncio.sleep(1800)     # check every 30 minutes

    # ── Proactive mode ──────────────────────────────────────────────────────────

    async def _run_proactive_mode(self) -> None:
        """
        Background task: periodically checks if the user has been silent long enough,
        then hands time + memory context to Gemini so it can decide what (if anything)
        to say proactively. No hardcoded rules — Gemini makes the call.
        """
        while True:
            await asyncio.sleep(60)   # evaluate once per minute

            if not self.session:
                continue

            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue

            if not self._proactive.should_trigger(self._last_user_speech):
                continue

            self._proactive.mark_triggered()

            try:
                memory       = await asyncio.to_thread(load_memory)
                monitors     = await asyncio.to_thread(list_monitors)
                recent_turns = self._session_log[-8:] if self._session_log else []
                prompt = self._proactive.build_prompt(
                    memory       = memory,
                    monitors     = monitors or None,
                    recent_turns = recent_turns or None,
                )
                await self._send_to_session(prompt)
                self.ui.write_log("SYS: Proactive check-in.")
            except Exception as e:
                print(f"[Proactive] ⚠️ {e}")

    # ── Stalled-session watchdog ──────────────────────────────────────────────

    async def _watchdog(self) -> None:
        """Force a reconnect only when the model is truly unresponsive to a
        finished utterance — never while the user is still speaking."""
        STALL_SECONDS = 20.0
        while True:
            await asyncio.sleep(5.0)
            if not self.session:
                continue
            if self._tool_busy or self._vision_busy:
                continue
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking or self.ui.muted:
                continue

            now = time.monotonic()
            # Never reconnect while the user is mid-utterance — the model is
            # expected to stay silent until end-of-speech is detected. This was
            # the cause of "JARVIS restarts while I speak".
            if self._eos.active:
                continue
            # Grace window after the user stopped talking, so a slow model
            # response is never mistaken for a dead connection.
            if now - self._eos.last_speech < 3.0:
                continue
            # Idle guard: skip when neither mic activity nor a pending EOS has
            # occurred recently.  We keep the watchdog alive as long as there is
            # a recent EOS (model owes us a response) even if the user stopped
            # speaking more than 10 s ago.
            if (now - self._mic_voice_time >= 10.0) and (now - self._last_eos_time >= 10.0):
                continue
            # Model has been silent too long after a finished utterance.
            if now - self._model_activity < STALL_SECONDS:
                continue

            print("[Watchdog] ⚠️ Model silent after user spoke — forcing reconnect.")
            self.ui.write_log("SYS: No response — reconnecting...")
            try:
                await self.session.close()
            except Exception:
                pass

    # ── Phone audio relay ────────────────────────────────────────────────────────

    async def _relay_phone_audio(self) -> None:
        """Forward phone mic PCM chunks from dashboard queue into the Gemini Live session."""
        q = self._dashboard._phone_audio_queue
        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # No audio for 1 s → phone mic inactive, give PC mic back
                self._phone_active = False
                continue
            self._phone_active = True   # phone is streaming — silence PC mic
            with self._speaking_lock:
                speaking = self._is_speaking
            if not speaking and not self.ui.muted:
                try:
                    self.out_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

    def _on_phone_connected(self) -> None:
        self.ui.write_log("SYS: Phone connected via Remote Dashboard.")
        self.ui.notify_phone_connected()

    # ── dashboard command relay ─────────────────────────────────────────────

    async def _process_dashboard_commands(self) -> None:
        while True:
            try:
                text = await asyncio.wait_for(
                    self._dashboard._command_queue.get(), timeout=0.5
                )
                if not text:
                    continue
                # Wait up to 8s for session to become ready after a wake
                for _ in range(80):
                    if self.session:
                        break
                    await asyncio.sleep(0.1)
                if self.session:
                    await self._send_to_session(text)
                    self.ui.write_log(f"[Web]: {text}")
                else:
                    print(f"[Dashboard] Dropped command (no session): {text}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)

    # ── main loop ───────────────────────────────────────────────────────────

    async def run(self):
        self._loop = asyncio.get_event_loop()

        # Start dashboard (optional — needs: pip install fastapi "uvicorn[standard]" cryptography)
        try:
            from dashboard.server import DashboardServer
            self._dashboard = DashboardServer()
            self._dashboard.set_connect_callback(self._on_phone_connected)
            asyncio.create_task(self._dashboard.serve())
            # Runs for the whole lifetime, not just inside an active session
            asyncio.create_task(self._process_dashboard_commands())
        except Exception as e:
            print(f"[Dashboard] Disabled: {e}")
            self._dashboard = None

        while True:
            try:
                print("[JARVIS] Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                # Fresh client on every reconnect — avoids stale HTTP session state
                client = genai.Client(
                    api_key=_get_api_key(),
                    http_options={
                        "api_version": "v1beta",
                        "async_client_args": {"open_timeout": 30},
                    }
                )

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session          = session
                    self.audio_in_queue   = asyncio.Queue(maxsize=300)
                    self.out_queue        = asyncio.Queue(maxsize=200)
                    self._turn_done_event = asyncio.Event()

                    # Reset transient state that must not carry over from a previous session
                    self._pending_vision       = None
                    self._vision_cam_active    = False
                    self._vision_close_pending = False
                    self._vision_busy          = False
                    self._vision_last_time     = 0.0
                    self._interrupted          = False
                    self._tool_busy            = False
                    self._mic_voice_time       = time.monotonic()
                    self._model_activity       = time.monotonic()
                    self._last_eos_time        = 0.0
                    self._post_speech_until    = 0.0
                    self._eos.reset()
                    self._barge.reset()
                    self._barge_active         = False

                    print("[JARVIS] Connected.")
                    self.ui.set_state(IDLE)
                    self.ui.write_log("SYS: JARVIS online.")

                    # A clean connection clears any accumulated reconnect
                    # backoff, so a one-off hiccup never leaves JARVIS waiting
                    # through a long 60s delay afterwards.
                    self._conn_backoff = 3

                    if self._dashboard:
                        await self._dashboard.broadcast({"type": "status", "state": "active"})

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._watchdog())
                    tg.create_task(self._run_system_monitor())
                    tg.create_task(self._run_background_monitor())
                    tg.create_task(self._run_proactive_mode())
                    if self._dashboard:
                        tg.create_task(self._relay_phone_audio())

                    # Morning briefing — fires once per process launch (if enabled)
                    if not self._briefing_sent and get_brief_enabled():
                        self._briefing_sent = True
                        tg.create_task(self._send_startup_briefing())

            except KeyboardInterrupt:
                raise
            except SystemExit:
                raise
            except BaseException as e:
                # Catches both Exception and BaseExceptionGroup (Python 3.11+
                # TaskGroup raises BaseExceptionGroup when tasks are cancelled
                # externally, which `except Exception` would miss, letting the
                # exception escape the while-loop and causing asyncio.run() to
                # start shutdown — resulting in "executor after shutdown" errors).
                err_str = str(e)
                print(f"[JARVIS] Error ({type(e).__name__}): {e}")
                traceback.print_exc()

                # The asyncio default executor has been shut down (Python 3.12+
                # asyncio.run() does this at loop teardown). This is unrecoverable
                # in-place — every reconnect would fail with "cannot schedule new
                # futures after shutdown" — so restart the whole process cleanly.
                if "cannot schedule new futures" in err_str or "shutdown" in err_str.lower():
                    print("[JARVIS] ⚠️ Executor shut down — restarting process…")
                    self.ui.write_log("SYS: Restarting to recover connection…")
                    import os as _os
                    if getattr(sys, "frozen", False):
                        _args = [sys.executable, *sys.argv[1:]]
                    else:
                        _args = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
                    try:
                        _os.execv(sys.executable, _args)
                    except Exception:
                        _os._exit(1)
                    return

                # Invalid API key — stop hammering the API, prompt re-configuration
                if "API key not valid" in err_str or "1007" in err_str:
                    self.ui.write_log("ERR: API key invalid — please re-enter your key.")
                    self.ui.set_state("SLEEPING")
                    self.ui.prompt_reconfig()
                    while not self.ui._win._ready:
                        await asyncio.sleep(1)
                    print("[JARVIS] New API key saved — reconnecting...")
                    self._conn_backoff = 3
                    continue

                # Network / timeout errors — log clearly and back off.
                # "CancelledError" is deliberately NOT treated as a network
                # error: it is the normal by-product of the watchdog (or any
                # task-group teardown) closing the session, and treating it as a
                # network failure made the reconnect backoff balloon to 60s,
                # which is why JARVIS looked "dead" until it was poked again.
                is_net_err = any(k in err_str for k in (
                    "TimeoutError", "timed out", "getaddrinfo",
                    "ConnectionRefusedError", "Cannot connect",
                    "WinError", "Network is unreachable", "Connection reset",
                    "RemoteDisconnected", "IncompleteRead",
                ))
                if is_net_err:
                    _conn_backoff = min(getattr(self, "_conn_backoff", 2) * 2, 30)
                    self._conn_backoff = _conn_backoff
                    self.ui.write_log(
                        f"NET: Нет соединения — повтор через {_conn_backoff}s. "
                        "(возможно, нужен VPN)"
                    )
                else:
                    self._conn_backoff = 3
            finally:
                self.session = None
                # Only save if there was a real conversation (≥3 turns)
                if len(self._session_log) >= 3:
                    asyncio.create_task(self._save_session_summary())

            self.set_speaking(False)
            # Brief "reconnecting" state instead of "SLEEPING" so JARVIS never
            # looks like it has gone to sleep during a quick reconnect.
            self.ui.set_state("THINKING")

            if self._dashboard:
                await self._dashboard.broadcast({"type": "status", "state": "sleeping"})

            delay = getattr(self, "_conn_backoff", 3)
            print(f"[JARVIS] Reconnecting in {delay}s...")
            await asyncio.sleep(delay)

def main():
    # Unhandled-exception safety net: log to a file instead of losing the
    # traceback, so a crash inside a Qt slot can be diagnosed after the fact.
    import traceback as _traceback
    def _excepthook(exc_type, exc, tb):
        try:
            _traceback.print_exception(exc_type, exc, tb)
            with open(BASE_DIR / "jarvis_crash.log", "a", encoding="utf-8") as _f:
                _f.write("=" * 60 + "\n")
                _f.write(f"[{datetime.now().isoformat()}] Unhandled {exc_type.__name__}: {exc}\n")
                _traceback.print_exception(exc_type, exc, tb, file=_f)
        except Exception:
            pass
    sys.excepthook = _excepthook

    # Resolve the face image relative to the script, not the launch directory,
    # so the startup face appears no matter where JARVIS is started from.
    _face = BASE_DIR / "face.png"
    ui = JarvisUI(str(_face) if _face.exists() else "face.png")

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    main()
