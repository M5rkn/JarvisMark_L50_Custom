from __future__ import annotations

import glob
import os
import time
import subprocess
import platform
import shutil

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

_SYSTEM = platform.system()

_APP_ALIASES: dict[str, dict[str, str]] = {

    "chrome":             {"Windows": "chrome",                  "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "google chrome":      {"Windows": "chrome",                  "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "firefox":            {"Windows": "firefox",                 "Darwin": "Firefox",              "Linux": "firefox"},
    "edge":               {"Windows": "msedge",                  "Darwin": "Microsoft Edge",       "Linux": "microsoft-edge"},
    "brave":              {"Windows": "brave",                   "Darwin": "Brave Browser",        "Linux": "brave-browser"},
    "safari":             {"Windows": "msedge",                  "Darwin": "Safari",               "Linux": "firefox"},
    "opera":              {"Windows": "opera",                   "Darwin": "Opera",                "Linux": "opera"},
    "whatsapp":           {"Windows": "WhatsApp",                "Darwin": "WhatsApp",             "Linux": "whatsapp"},
    "telegram":           {"Windows": "Telegram",                "Darwin": "Telegram",             "Linux": "telegram"},
    "discord":            {"Windows": "Discord",                 "Darwin": "Discord",              "Linux": "discord"},
    "slack":              {"Windows": "Slack",                   "Darwin": "Slack",                "Linux": "slack"},
    "zoom":               {"Windows": "Zoom",                    "Darwin": "zoom.us",              "Linux": "zoom"},
    "teams":              {"Windows": "msteams",                 "Darwin": "Microsoft Teams",      "Linux": "teams"},
    "skype":              {"Windows": "skype",                   "Darwin": "Skype",                "Linux": "skype"},
    "signal":             {"Windows": "signal",                  "Darwin": "Signal",               "Linux": "signal"},
    "spotify":            {"Windows": "Spotify",                 "Darwin": "Spotify",              "Linux": "spotify"},
    "vlc":                {"Windows": "vlc",                     "Darwin": "VLC",                  "Linux": "vlc"},
    "netflix":            {"Windows": "Netflix",                 "Darwin": "Netflix",              "Linux": "firefox"},
    "vscode":             {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "visual studio code": {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "code":               {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "terminal":           {"Windows": "wt",                      "Darwin": "Terminal",             "Linux": "x-terminal-emulator"},
    "cmd":                {"Windows": "cmd.exe",                 "Darwin": "Terminal",             "Linux": "bash"},
    "powershell":         {"Windows": "powershell.exe",          "Darwin": "Terminal",             "Linux": "bash"},
    "postman":            {"Windows": "Postman",                 "Darwin": "Postman",              "Linux": "postman"},
    "git":                {"Windows": "git-bash",                "Darwin": "Terminal",             "Linux": "bash"},
    "figma":              {"Windows": "Figma",                   "Darwin": "Figma",                "Linux": "figma"},
    "blender":            {"Windows": "blender",                 "Darwin": "Blender",              "Linux": "blender"},
    "word":               {"Windows": "winword",                 "Darwin": "Microsoft Word",       "Linux": "libreoffice --writer"},
    "excel":              {"Windows": "excel",                   "Darwin": "Microsoft Excel",      "Linux": "libreoffice --calc"},
    "powerpoint":         {"Windows": "powerpnt",                "Darwin": "Microsoft PowerPoint", "Linux": "libreoffice --impress"},
    "libreoffice":        {"Windows": "soffice",                 "Darwin": "LibreOffice",          "Linux": "libreoffice"},
    "notepad":            {"Windows": "notepad.exe",             "Darwin": "TextEdit",             "Linux": "gedit"},
    "textedit":           {"Windows": "notepad.exe",             "Darwin": "TextEdit",             "Linux": "gedit"},
    "explorer":           {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "file explorer":      {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "finder":             {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "task manager":       {"Windows": "taskmgr.exe",             "Darwin": "Activity Monitor",     "Linux": "gnome-system-monitor"},
    "settings":           {"Windows": "ms-settings:",            "Darwin": "System Preferences",   "Linux": "gnome-control-center"},
    "control panel":      {"Windows": "control",                 "Darwin": "System Preferences",   "Linux": "gnome-control-center"},
    "power management":   {"Windows": "powercfg.cpl",            "Darwin": "System Preferences",   "Linux": "gnome-power-statistics"},
    "power options":      {"Windows": "powercfg.cpl",            "Darwin": "System Preferences",   "Linux": "gnome-power-statistics"},
    "power and sleep":    {"Windows": "ms-settings:powersleep",  "Darwin": "System Preferences",   "Linux": "gnome-power-statistics"},
    "device manager":     {"Windows": "devmgmt.msc",             "Darwin": "System Information",   "Linux": ""},
    "network connections":{"Windows": "ncpa.cpl",                "Darwin": "System Preferences",   "Linux": "nm-connection-editor"},
    "network settings":   {"Windows": "ms-settings:network",     "Darwin": "System Preferences",   "Linux": "gnome-control-center"},
    "wifi settings":      {"Windows": "ms-settings:network-wifi","Darwin": "System Preferences",   "Linux": "gnome-control-center"},
    "bluetooth settings": {"Windows": "ms-settings:bluetooth",   "Darwin": "System Preferences",   "Linux": "gnome-control-center"},
    "управление электропитанием": {"Windows": "powercfg.cpl",    "Darwin": "System Preferences",   "Linux": "gnome-power-statistics"},
    "диспетчер устройств": {"Windows": "devmgmt.msc",            "Darwin": "System Information",   "Linux": ""},
    "сетевые подключения": {"Windows": "ncpa.cpl",               "Darwin": "System Preferences",   "Linux": "nm-connection-editor"},
    "calculator":         {"Windows": "calc.exe",                "Darwin": "Calculator",           "Linux": "gnome-calculator"},
    "paint":              {"Windows": "mspaint.exe",             "Darwin": "Preview",              "Linux": "gimp"},
    "instagram":          {"Windows": "Instagram",               "Darwin": "Instagram",            "Linux": "firefox"},
    "tiktok":             {"Windows": "TikTok",                  "Darwin": "TikTok",               "Linux": "firefox"},
    "notion":             {"Windows": "Notion",                  "Darwin": "Notion",               "Linux": "notion"},
    "obsidian":           {"Windows": "Obsidian",                "Darwin": "Obsidian",             "Linux": "obsidian"},
    "capcut":             {"Windows": "CapCut",                  "Darwin": "CapCut",               "Linux": "capcut"},
    "steam":              {"Windows": "steam",                   "Darwin": "Steam",                "Linux": "steam"},
    "epic":               {"Windows": "EpicGamesLauncher",       "Darwin": "Epic Games Launcher",  "Linux": "legendary"},
    "epic games":         {"Windows": "EpicGamesLauncher",       "Darwin": "Epic Games Launcher",  "Linux": "legendary"},
}


def _normalize(raw: str) -> str:
    key = raw.lower().strip()

    if key in _APP_ALIASES:
        return _APP_ALIASES[key].get(_SYSTEM, raw)

    for alias_key, os_map in _APP_ALIASES.items():
        if alias_key in key or key in alias_key:
            return os_map.get(_SYSTEM, raw)

    return raw


def _is_desktop_app(app_name: str) -> bool:
    """True if app_name refers to a known desktop application (has an alias)."""
    key = app_name.lower().strip()
    if not key:
        return False
    if key in _APP_ALIASES:
        return True
    for alias_key in _APP_ALIASES:
        if alias_key in key or key in alias_key:
            return True
    return False


# Web services — these always open in the browser, never as desktop apps.
_WEB_APPS: dict[str, str] = {
    "spotify":       "https://open.spotify.com",
    "youtube":       "https://www.youtube.com",
    "netflix":       "https://www.netflix.com",
    "twitch":        "https://www.twitch.tv",
    "instagram":     "https://www.instagram.com",
    "tiktok":        "https://www.tiktok.com",
    "reddit":        "https://www.reddit.com",
    "twitter":       "https://x.com",
    "facebook":      "https://www.facebook.com",
    "gmail":         "https://mail.google.com",
    "google docs":   "https://docs.google.com",
    "docs":          "https://docs.google.com",
    "google drive":  "https://drive.google.com",
    "drive":         "https://drive.google.com",
    "google meet":   "https://meet.google.com",
    "google maps":   "https://maps.google.com",
    "maps":          "https://maps.google.com",
    "translate":     "https://translate.google.com",
    "google translate": "https://translate.google.com",
    "github":        "https://github.com",
    "chatgpt":       "https://chatgpt.com",
    "notion":        "https://www.notion.so",
    "figma":         "https://www.figma.com",
    "whatsapp web":  "https://web.whatsapp.com",
}


def _web_app_match(app_name: str) -> tuple[str | None, str | None]:
    """Return (url, keyword) if app_name is a web service, else (None, None)."""
    key = app_name.lower().strip()
    if key in _WEB_APPS:
        return _WEB_APPS[key], key
    for k, url in _WEB_APPS.items():
        if k in key or key in k:
            return url, k
    return None, None


def _open_in_browser(url: str) -> bool:
    try:
        if _SYSTEM == "Windows":
            os.startfile(url)  # type: ignore[attr-defined]
        elif _SYSTEM == "Darwin":
            subprocess.run(["open", url], check=True, timeout=10)
        else:
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return True
    except Exception as e:
        print(f"[open_app] browser open failed: {e}")
        return False


_WINDOWS_START_MENU_DIRS = [
    os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
    os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
]


def _find_windows_shortcut(app_name: str) -> str | None:
    """Find the best Start Menu .lnk for the given app name."""
    query = app_name.lower().strip()
    if not query:
        return None

    best_path: str | None = None
    best_score = -1

    for base in _WINDOWS_START_MENU_DIRS:
        if not os.path.isdir(base):
            continue
        for lnk in glob.glob(os.path.join(base, "**", "*.lnk"), recursive=True):
            stem = os.path.splitext(os.path.basename(lnk))[0].lower()
            if stem == query:
                return lnk
            if query in stem or stem in query:
                score = 100 - abs(len(stem) - len(query))
                if score > best_score:
                    best_score = score
                    best_path = lnk

    return best_path


def _launch_via_startfile(target: str) -> bool:
    try:
        os.startfile(target)  # type: ignore[attr-defined]
        time.sleep(1.5)
        return True
    except OSError as e:
        print(f"[open_app] startfile failed: {e}")
        return False


def _launch_windows_start_search(app_name: str) -> bool:
    """Fallback: open Start Menu search and paste the app name."""
    try:
        import pyautogui
        pyautogui.PAUSE = 0.1
        pyautogui.press("win")
        time.sleep(0.7)

        if _PYPERCLIP:
            pyperclip.copy(app_name)
            time.sleep(0.15)
            pyautogui.hotkey("ctrl", "v")
        else:
            pyautogui.write(app_name, interval=0.05)

        time.sleep(0.9)
        pyautogui.press("enter")
        time.sleep(2.5)
        return True
    except Exception as e:
        print(f"[open_app] Start Menu search failed: {e}")
        return False


def _launch_windows(app_name: str) -> bool:

    if shutil.which(app_name) or shutil.which(app_name.split(".")[0]):
        try:
            subprocess.Popen(
                app_name,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1.5)
            return True
        except Exception as e:
            print(f"[open_app] subprocess failed: {e}")

    shortcut = _find_windows_shortcut(app_name)
    if shortcut and _launch_via_startfile(shortcut):
        return True

    if ":" in app_name:
        try:
            subprocess.Popen(f"start {app_name}", shell=True)
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", app_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1.5)
        return True
    except Exception as e:
        print(f"[open_app] cmd start failed: {e}")

    return _launch_windows_start_search(app_name)


def _launch_macos(app_name: str) -> bool:

    try:
        result = subprocess.run(
            ["open", "-a", app_name],
            capture_output=True, timeout=8
        )
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["open", "-a", f"{app_name}.app"],
            capture_output=True, timeout=8
        )
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    binary = shutil.which(app_name) or shutil.which(app_name.lower())
    if binary:
        try:
            subprocess.Popen(
                [binary],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        import pyautogui
        pyautogui.hotkey("command", "space")
        time.sleep(0.6)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(1.5)
        return True
    except Exception as e:
        print(f"[open_app] Spotlight failed: {e}")

    return False


_LINUX_TERMINAL_FALLBACKS = [
    "x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal",
    "xterm", "lxterminal", "mate-terminal", "tilix", "alacritty", "kitty",
]

def _launch_linux(app_name: str) -> bool:

    # terminal emulators: try common ones in order
    if app_name in ("x-terminal-emulator", "gnome-terminal", "terminal"):
        for term in _LINUX_TERMINAL_FALLBACKS:
            if shutil.which(term):
                try:
                    subprocess.Popen([term], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(1.0)
                    return True
                except Exception:
                    continue

    binary = (
        shutil.which(app_name) or
        shutil.which(app_name.lower()) or
        shutil.which(app_name.lower().replace(" ", "-")) or
        shutil.which(app_name.lower().replace(" ", "_"))
    )
    if binary:
        try:
            subprocess.Popen(
                [binary],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        subprocess.run(
            ["xdg-open", app_name],
            capture_output=True, timeout=5
        )
        return True
    except Exception:
        pass

    for desktop_name in [
        app_name.lower(),
        app_name.lower().replace(" ", "-"),
        app_name.lower().replace(" ", ""),
    ]:
        try:
            result = subprocess.run(
                ["gtk-launch", desktop_name],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass

    return False


_OS_LAUNCHERS = {
    "Windows": _launch_windows,
    "Darwin":  _launch_macos,
    "Linux":   _launch_linux,
}


def _focus_existing_window(app_name: str, normalized: str) -> bool:
    """Bring an already-open window for this app to the front. Returns True if focused."""
    needles = {n.lower().strip() for n in (app_name, normalized) if n and n.strip()}
    if not needles:
        return False
    try:
        if _SYSTEM == "Windows":
            import pygetwindow as gw
            best = None
            for w in gw.getAllWindows():
                t = (w.title or "").lower()
                if any(n in t for n in needles) and w.width > 40 and w.height > 40:
                    if best is None or (w.width * w.height) > (best.width * best.height):
                        best = w
            if best is None:
                return False
            try:
                if best.isMinimized:
                    best.restore()
                best.activate()
            except Exception:
                pass
            return True

        if _SYSTEM == "Darwin":
            for n in sorted(needles, key=len, reverse=True):
                r = subprocess.run(
                    ["osascript", "-e", f'tell application "{n}" to activate'],
                    capture_output=True, timeout=5,
                )
                if r.returncode == 0:
                    return True
            return False

        # Linux
        try:
            for n in sorted(needles, key=len, reverse=True):
                if subprocess.run(
                    ["wmctrl", "-a", n], capture_output=True, timeout=5
                ).returncode == 0:
                    return True
        except FileNotFoundError:
            pass
        return False
    except Exception as e:
        print(f"[open_app] focus failed: {e}")
        return False


def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    app_name = (parameters or {}).get("app_name", "").strip()

    if not app_name:
        return "No application name provided."

    # Web services (Spotify, YouTube, Netflix, …) always open in the browser:
    # switch to an existing tab if present, otherwise open a new browser tab.
    web_url, web_kw = _web_app_match(app_name)
    if web_url:
        try:
            from actions.browser_control import switch_chrome_tab
            if switch_chrome_tab(web_kw):
                return f"Switched to the existing {app_name} tab."
        except Exception:
            pass
        if _open_in_browser(web_url):
            return f"Opened {app_name} in the browser."

    launcher = _OS_LAUNCHERS.get(_SYSTEM)
    if launcher is None:
        return f"Unsupported operating system: {_SYSTEM}"

    normalized = _normalize(app_name)
    print(f"[open_app] Launching: '{app_name}' → '{normalized}' ({_SYSTEM})")

    if player:
        player.write_log(f"[open_app] {app_name}")

    # If the app is already open, switch to its existing window instead of
    # launching a second instance.
    if _focus_existing_window(app_name, normalized):
        return f"Focused the existing {app_name} window."

    # Not a running desktop app — maybe it's open as a Chrome tab. Switch to it
    # instead of launching a new instance. Skip this for known desktop apps:
    # e.g. "Telegram" must launch the desktop client, not the Telegram Web tab.
    if not _is_desktop_app(app_name):
        try:
            from actions.browser_control import switch_chrome_tab
            if switch_chrome_tab(normalized):
                return f"Switched to the existing {app_name} tab."
        except Exception:
            pass

    try:
        if launcher(normalized):
            return f"Opened {app_name}."
        if normalized.lower() != app_name.lower():
            if launcher(app_name):
                return f"Opened {app_name}."
        return (
            f"Could not confirm that {app_name} launched. "
            f"It may still be loading, or it might not be installed."
        )
    except Exception as e:
        print(f"[open_app] Error: {e}")
        return f"Failed to open {app_name}: {e}"