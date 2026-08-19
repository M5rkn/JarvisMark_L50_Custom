"""Tool declarations for JARVIS — moved here from main.py to keep it navigable."""
from __future__ import annotations

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

# ── Core vs. skill-owned tool routing ─────────────────────────────────────────
# The tool names below remain handled inline by JarvisLive (lifecycle, vision,
# memory). Every other tool is now owned by a skill under skills/ and is routed
# through SkillManager (skills/manager.py). The legacy TOOL_DECLARATIONS list is
# kept as the schema source; CORE_TOOL_DECLARATIONS extracts only the core names
# from it so the modular system is the single source of truth for enable/disable.
_CORE_TOOL_NAMES = {
    "get_current_time",
    "screen_process",
    "close_camera",
    "manage_monitor",
    "shutdown_jarvis",
    "restart_jarvis",
    "save_memory",
    "add_memory",
    "recall_memory",
}

CORE_TOOL_DECLARATIONS = [
    t for t in TOOL_DECLARATIONS if t["name"] in _CORE_TOOL_NAMES
]

# Tools that let JARVIS manage the skill system itself (create / list / remove /
# disable / enable skills) — always available, never disabled.
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
