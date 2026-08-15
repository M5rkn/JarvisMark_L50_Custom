
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import platform
import re
import shutil
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
)
_OS = platform.system()   # "Windows" | "Darwin" | "Linux"
_CDP_PORT = 9222          # Chrome remote-debugging port (attach to the real browser)

# Chromium browsers share the "Chrome_WidgetWin_1" window class, so UI
# Automation tab control must filter by process name. Firefox has a different
# accessibility tree and is handled via the Playwright session instead.
_UIA_EXE_BY_BROWSER = {
    "chrome":  "chrome.exe",
    "edge":    "msedge.exe",
    "brave":   "brave.exe",
    "vivaldi": "vivaldi.exe",
    "opera":   "opera.exe",
    "operagx": "opera.exe",
}

def _normalize_url(url: str) -> str:
    """
    Bare words like "instagram" → "https://instagram.com"
    Domains like "instagram.com" → "https://instagram.com"
    Full URLs pass through unchanged.
    """
    url = url.strip()
    if not url:
        return "about:blank"
    if "://" in url:
        return url
    # No dot at all → assume .com  (e.g. "instagram" → "instagram.com")
    if "." not in url:
        url = url + ".com"
    return "https://" + url


def _site_keyword(url: str) -> str:
    """Extract a window-title keyword from a URL, e.g. 'spotify' from open.spotify.com."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        parts = [p for p in host.split(".") if p]
        if len(parts) >= 3:
            return parts[-2]
        return parts[0] if parts else ""
    except Exception:
        return ""


def _focus_existing_window(keyword: str) -> bool:
    """Bring an already-open window/tab whose title contains keyword to the front."""
    keyword = (keyword or "").lower().strip()
    if not keyword:
        return False
    try:
        if _OS == "Windows":
            import pygetwindow as gw
            best = None
            for w in gw.getAllWindows():
                t = (w.title or "").lower()
                if keyword in t and w.width > 80 and w.height > 80:
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

        if _OS == "Darwin":
            script = (
                'tell application "System Events" to set frontmost of '
                f'(first process whose name contains "{keyword}") to true'
            )
            return subprocess.run(
                ["osascript", "-e", script], capture_output=True, timeout=5
            ).returncode == 0

        # Linux
        try:
            return subprocess.run(
                ["wmctrl", "-a", keyword], capture_output=True, timeout=5
            ).returncode == 0
        except FileNotFoundError:
            return False
    except Exception as e:
        print(f"[Browser] focus existing window failed: {e}")
        return False


def switch_chrome_tab(keyword: str) -> bool:
    """
    Switch to an existing Chrome tab (including background tabs) whose title
    contains `keyword`. Windows-only, Chrome-only. Returns True if switched.
    Uses UI Automation (pywinauto) — the same pattern as game_updater.py.
    """
    keyword = (keyword or "").lower().strip()
    if _OS != "Windows" or not keyword:
        return False
    try:
        from pywinauto import Application, findwindows
    except ImportError:
        return False

    def _tab_title(tab) -> str:
        try:
            t = tab.window_text()
            if t:
                return t.lower()
            # Fallback: some Chrome builds expose the title on child text nodes
            parts = [c.window_text() for c in tab.children() if c.window_text()]
            return " ".join(parts).lower()
        except Exception:
            return ""

    try:
        hwnds = findwindows.find_windows(
            class_name="Chrome_WidgetWin_1", active_only=False
        )
        if not hwnds:
            # Fallback: find by process name chrome.exe
            import psutil
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if (proc.info["name"] or "").lower() == "chrome.exe":
                        hwnds.extend(findwindows.find_windows(
                            process=proc.info["pid"], active_only=False
                        ))
                except Exception:
                    continue

        for hwnd in hwnds:
            try:
                app = Application(backend="uia").connect(handle=hwnd)
                win = app.window(handle=hwnd)
                if not win.is_visible():
                    continue
                rect = win.rectangle()
                if rect.width() < 300 or rect.height() < 200:
                    continue

                for tab in win.descendants(control_type="TabItem"):
                    title = _tab_title(tab)
                    if not title or keyword not in title:
                        continue
                    # Found the tab — bring the window up, then select it
                    try:
                        if win.is_minimized():
                            win.restore()
                        win.set_focus()
                    except Exception:
                        pass
                    try:
                        tab.select()
                    except Exception:
                        try:
                            tab.click_input()
                        except Exception:
                            pass
                    return True
            except Exception:
                continue
    except Exception as e:
        print(f"[Browser] chrome tab switch failed: {e}")
    return False


def close_chrome_tab_by_name(keyword: str, browser: str = "chrome") -> str:
    """
    Close an existing Chromium-browser tab (including background tabs) whose
    title matches `keyword`. Windows-only. Returns a human-readable result
    string describing the outcome. Uses UI Automation (pywinauto) — the same
    pattern as switch_chrome_tab.
    """
    keyword = (keyword or "").lower().strip()
    if _OS != "Windows" or not keyword:
        return "Closing a tab by name is only supported on Windows."

    name     = _ALIASES.get(browser.lower().strip(), browser.lower().strip()) if browser else "chrome"
    exe_name = _UIA_EXE_BY_BROWSER.get(name)
    if not exe_name:
        return f"Closing tabs by name is not supported for '{name}'."

    try:
        from pywinauto import Application, findwindows
    except ImportError:
        return "pywinauto is not installed."

    def _tab_title(tab) -> str:
        try:
            t = tab.window_text()
            if t:
                return t
            # Fallback: some Chrome builds expose the title on child text nodes
            parts = [c.window_text() for c in tab.children() if c.window_text()]
            return " ".join(parts)
        except Exception:
            return ""

    def _matches(title: str) -> bool:
        title_l = title.lower()
        if keyword in title_l:
            return True
        # Token fallback: every keyword token must appear somewhere in the title
        # (handles "close the Telegram tab" → title "Telegram Web", etc.)
        tokens = [t for t in re.split(r"[^a-zа-яё0-9]+", keyword) if t]
        if not tokens:
            return False
        return all(tok in title_l for tok in tokens)

    def _find_hwnds():
        # Chromium and Electron apps (VS Code, Discord, Slack…) share the
        # "Chrome_WidgetWin_1" window class, so enumerate windows by the target
        # browser's process name to avoid touching those other apps.
        hwnds = []
        try:
            import psutil
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if (proc.info["name"] or "").lower() == exe_name:
                        hwnds.extend(findwindows.find_windows(
                            process=proc.info["pid"], active_only=False
                        ))
                except Exception:
                    continue
        except Exception:
            pass
        if hwnds:
            return hwnds
        # Last-resort fallback: window class (may also match other Chromium apps).
        try:
            return list(findwindows.find_windows(
                class_name="Chrome_WidgetWin_1", active_only=False
            ))
        except Exception:
            return []

    hwnds = _find_hwnds()
    if not hwnds:
        return "Chrome is not running."

    seen_titles: list[str] = []

    for hwnd in hwnds:
        try:
            app = Application(backend="uia").connect(handle=hwnd)
            win = app.window(handle=hwnd)
            rect = win.rectangle()
            if rect.width() < 300 or rect.height() < 200:
                continue

            # Chrome builds its accessibility tree lazily — retry a few times
            # so a fresh connection doesn't return an empty tab list.
            tabs = []
            for _ in range(4):
                tabs = win.descendants(control_type="TabItem")
                if tabs:
                    break
                time.sleep(0.6)

            for tab in tabs:
                title = _tab_title(tab).strip()
                if title and title not in seen_titles:
                    seen_titles.append(title)
                if not title or not _matches(title):
                    continue

                # Found the tab — activate it, then close it with Ctrl+W
                try:
                    if win.is_minimized():
                        win.restore()
                    win.set_focus()
                except Exception:
                    pass
                try:
                    tab.select()
                except Exception:
                    try:
                        tab.click_input()
                    except Exception:
                        pass
                time.sleep(0.3)
                try:
                    win.type_keys("^w")
                except Exception:
                    try:
                        import pyautogui
                        pyautogui.hotkey("ctrl", "w")
                    except Exception:
                        pass
                return f"Closed the '{title}' tab."
        except Exception as e:
            print(f"[Browser] chrome tab close failed: {e}")

    if seen_titles:
        listed = ", ".join(f"'{t}'" for t in seen_titles)
        return f"Could not find a tab named '{keyword}'. Open tabs: {listed}"
    return f"Could not find a tab named '{keyword}'. No accessible tabs in Chrome."


def _chrome_exe() -> Optional[str]:
    exe = _find_exe_windows("chrome")
    if exe:
        return exe
    local  = os.environ.get("LOCALAPPDATA", "")
    prog   = os.environ.get("PROGRAMFILES", "")
    prog86 = os.environ.get("PROGRAMFILES(X86)", "")
    for p in (
        Path(local)  / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(prog)   / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(prog86) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ):
        if p.exists():
            return str(p)
    return shutil.which("chrome") or shutil.which("chrome.exe")


def _chrome_running() -> bool:
    try:
        import psutil
        for proc in psutil.process_iter(["name"]):
            try:
                if (proc.info["name"] or "").lower() == "chrome.exe":
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/NH"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        return "chrome.exe" in out.lower()
    except Exception:
        pass
    return False


def _kill_chrome_and_wait() -> None:
    """Force-close Chrome and wait until no chrome.exe process remains."""
    for _ in range(5):
        try:
            subprocess.run(
                ["taskkill", "/IM", "chrome.exe", "/F", "/T"],
                capture_output=True, timeout=20,
            )
        except Exception as e:
            print(f"[Browser] taskkill chrome failed: {e}")
        try:
            import psutil
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if (proc.info["name"] or "").lower() == "chrome.exe":
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass
        time.sleep(2.0)
        if not _chrome_running():
            return
    time.sleep(2.0)


def _wait_for_cdp(timeout: float = 30.0) -> bool:
    import urllib.request
    # Bypass any system proxy — the CDP endpoint is localhost-only.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        for host in ("127.0.0.1", "localhost"):
            try:
                with opener.open(
                    f"http://{host}:{_CDP_PORT}/json/version", timeout=2
                ) as r:
                    if r.status == 200:
                        return True
            except Exception:
                continue
        time.sleep(0.8)
    return False


def launch_chrome_control_mode() -> str:
    """
    Close Chrome and relaunch it with --remote-debugging-port so JARVIS can
    attach via CDP and manage the real browser (its tabs, URLs, sessions).
    Windows-only. Tabs are restored via --restore-last-session.
    """
    if _OS != "Windows":
        return "Chrome control mode is currently supported on Windows only."

    exe = _chrome_exe()
    if not exe:
        return "Could not find Chrome on this system."

    # 1) Close Chrome and wait until it is fully gone, so the debug flag is
    #    not swallowed by an already-running instance.
    _kill_chrome_and_wait()

    # 2) Relaunch with remote debugging on IPv4 localhost + session restore.
    try:
        subprocess.Popen(
            [exe,
             f"--remote-debugging-port={_CDP_PORT}",
             "--remote-debugging-address=127.0.0.1",
             "--restore-last-session",
             "--start-maximized",
             "--no-first-run",
             "--no-default-browser-check"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return f"Failed to relaunch Chrome: {e}"

    # 3) Wait for the CDP endpoint.
    if _wait_for_cdp(30):
        return (f"Chrome is now in control mode (CDP port {_CDP_PORT}). "
                f"I can manage its tabs.")

    if _chrome_running():
        return ("Chrome is running, but the control port did not open. "
                "Close Chrome completely, then try again.")
    return "Chrome did not start. Please try again."


# ── Workspaces: named sets of tabs, persisted to ~/.jarvis/workspaces.json ──

_WORKSPACES_PATH = Path.home() / ".jarvis" / "workspaces.json"


def _load_workspaces() -> dict:
    try:
        if _WORKSPACES_PATH.exists():
            return json.loads(_WORKSPACES_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[Browser] load workspaces failed: {e}")
    return {}


def _save_workspaces(data: dict) -> None:
    try:
        _WORKSPACES_PATH.parent.mkdir(parents=True, exist_ok=True)
        _WORKSPACES_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[Browser] save workspaces failed: {e}")


def _user_agent() -> str:
    if _OS == "Windows":
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    if _OS == "Darwin":
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    return (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )


def _real_profile_dir(browser: str) -> str:
    home  = Path.home()
    local = os.environ.get("LOCALAPPDATA", "")
    roam  = os.environ.get("APPDATA", "")

    candidates: list[Path] = []

    if _OS == "Windows":
        m = {
            "chrome":   [Path(local) / "Google"          / "Chrome"          / "User Data"],
            "edge":     [Path(local) / "Microsoft"        / "Edge"            / "User Data"],
            "brave":    [Path(local) / "BraveSoftware"    / "Brave-Browser"   / "User Data"],
            "vivaldi":  [Path(local) / "Vivaldi"          / "User Data"],
            "opera":    [Path(roam)  / "Opera Software"   / "Opera Stable",
                         Path(local) / "Opera Software"   / "Opera Stable"],
            "operagx":  [Path(roam)  / "Opera Software"   / "Opera GX Stable",
                         Path(local) / "Opera Software"   / "Opera GX Stable"],
        }
        candidates = m.get(browser, [])

    elif _OS == "Darwin":
        lib = home / "Library" / "Application Support"
        m = {
            "chrome":   [lib / "Google"             / "Chrome"],
            "edge":     [lib / "Microsoft Edge"],
            "brave":    [lib / "BraveSoftware"       / "Brave-Browser"],
            "vivaldi":  [lib / "Vivaldi"],
            "opera":    [lib / "com.operasoftware.Opera"],
            "operagx":  [lib / "com.operasoftware.OperaGX"],
        }
        candidates = m.get(browser, [])

    elif _OS == "Linux":
        cfg = home / ".config"
        m = {
            "chrome":   [cfg / "google-chrome", cfg / "chromium"],
            "edge":     [cfg / "microsoft-edge"],
            "brave":    [cfg / "BraveSoftware" / "Brave-Browser"],
            "vivaldi":  [cfg / "vivaldi"],
            "opera":    [cfg / "opera"],
            "operagx":  [cfg / "opera-gx"],
        }
        candidates = m.get(browser, [])

    for p in candidates:
        if p.exists():
            print(f"[Browser] ✅ Real profile found for {browser}: {p}")
            return str(p)

    fallback = home / ".jarvis_profiles" / browser
    fallback.mkdir(parents=True, exist_ok=True)
    print(f"[Browser] ⚠️  Real profile not found for {browser}, using: {fallback}")
    return str(fallback)

def _firefox_profile_dir() -> Optional[str]:
    home = Path.home()

    if _OS == "Windows":
        base = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox"
    elif _OS == "Darwin":
        base = home / "Library" / "Application Support" / "Firefox"
    else:
        base = home / ".mozilla" / "firefox"

    ini = base / "profiles.ini"
    if not ini.exists():
        return None

    current: dict[str, str] = {}
    default_path: Optional[str] = None

    for line in ini.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("["):
            p = current.get("Path", "")
            if p and current.get("Default") == "1":
                is_rel = current.get("IsRelative", "1") == "1"
                default_path = str(base / p) if is_rel else p
            current = {}
        elif "=" in line:
            k, _, v = line.partition("=")
            current[k.strip()] = v.strip()

    p = current.get("Path", "")
    if p and current.get("Default") == "1":
        is_rel = current.get("IsRelative", "1") == "1"
        default_path = str(base / p) if is_rel else p

    if default_path and Path(default_path).exists():
        print(f"[Browser] Firefox real profile: {default_path}")
        return default_path
    return None

def _find_opera_windows() -> Optional[str]:
    local  = os.environ.get("LOCALAPPDATA", "")
    prog   = os.environ.get("PROGRAMFILES", "")
    prog86 = os.environ.get("PROGRAMFILES(X86)", "")

    candidates = [
        Path(local)  / "Programs" / "Opera"    / "opera.exe",
        Path(local)  / "Programs" / "Opera GX" / "opera.exe",
        Path(prog)   / "Opera"    / "opera.exe",
        Path(prog86) / "Opera"    / "opera.exe",
    ]
    for p in candidates:
        if p.exists():
            print(f"[Browser] Opera found at: {p}")
            return str(p)

    try:
        import winreg
        keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\opera.exe",
            r"SOFTWARE\Clients\StartMenuInternet\OperaStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\OperaGXStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\opera\shell\open\command",
        ]
        for key_path in keys:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    k   = winreg.OpenKey(hive, key_path)
                    val = winreg.QueryValue(k, None)
                    winreg.CloseKey(k)
                    exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        print(f"[Browser] Opera found via registry: {exe}")
                        return exe
                except Exception:
                    continue
    except Exception:
        pass

    return shutil.which("opera") or None

def _find_exe_windows(prog_name: str) -> Optional[str]:
    try:
        import winreg
        paths_to_try = [
            rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{prog_name}.exe",
            rf"SOFTWARE\Clients\StartMenuInternet\{prog_name}\shell\open\command",
        ]
        for key_path in paths_to_try:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    k   = winreg.OpenKey(hive, key_path)
                    val = winreg.QueryValue(k, None)
                    winreg.CloseKey(k)
                    exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        return exe
                except Exception:
                    continue
    except Exception:
        pass
    return None

_BROWSER_SPECS: dict[str, dict] = {
    "Windows": {
        "chrome":   {"engine": "chromium", "channel": "chrome",  "bins": []},
        "edge":     {"engine": "chromium", "channel": "msedge",  "bins": []},
        "firefox":  {"engine": "firefox",  "channel": None,      "bins": ["firefox.exe"]},
        "opera":    {"engine": "chromium", "channel": None,      "bins": ["opera.exe"],  "special": "opera_windows"},
        "operagx":  {"engine": "chromium", "channel": None,      "bins": [],             "special": "opera_windows"},
        "brave":    {"engine": "chromium", "channel": None,      "bins": ["brave.exe"]},
        "vivaldi":  {"engine": "chromium", "channel": None,      "bins": ["vivaldi.exe"]},
        "safari":   None,
    },
    "Darwin": {
        "chrome":   {"engine": "chromium", "channel": "chrome",  "bins": []},
        "edge":     {"engine": "chromium", "channel": "msedge",  "bins": ["microsoft-edge"]},
        "firefox":  {"engine": "firefox",  "channel": None,      "bins": ["firefox"]},
        "opera":    {"engine": "chromium", "channel": None,      "bins": ["opera"]},
        "operagx":  {"engine": "chromium", "channel": None,      "bins": ["opera"]},
        "brave":    {"engine": "chromium", "channel": None,      "bins": ["brave browser", "brave"]},
        "vivaldi":  {"engine": "chromium", "channel": None,      "bins": ["vivaldi"]},
        "safari":   {"engine": "webkit",   "channel": None,      "bins": []},
    },
    "Linux": {
        "chrome":   {"engine": "chromium", "channel": None,
                     "bins": ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]},
        "edge":     {"engine": "chromium", "channel": None,
                     "bins": ["microsoft-edge", "microsoft-edge-stable"]},
        "firefox":  {"engine": "firefox",  "channel": None, "bins": ["firefox"]},
        "opera":    {"engine": "chromium", "channel": None, "bins": ["opera", "opera-stable"]},
        "operagx":  {"engine": "chromium", "channel": None, "bins": ["opera", "opera-stable"]},
        "brave":    {"engine": "chromium", "channel": None, "bins": ["brave-browser", "brave"]},
        "vivaldi":  {"engine": "chromium", "channel": None, "bins": ["vivaldi-stable", "vivaldi"]},
        "safari":   None,
    },
}

_ALIASES: dict[str, str] = {
    "google chrome":   "chrome",
    "google-chrome":   "chrome",
    "microsoft edge":  "edge",
    "ms edge":         "edge",
    "msedge":          "edge",
    "mozilla firefox": "firefox",
    "opera gx":        "operagx",
    "opera_gx":        "operagx",
}


def _resolve_browser(name: str) -> dict | None:
    name   = _ALIASES.get(name.lower().strip(), name.lower().strip())
    os_map = _BROWSER_SPECS.get(_OS, {})
    spec   = os_map.get(name)
    if spec is None:
        return None

    engine  = spec["engine"]
    channel = spec.get("channel")
    bins    = spec.get("bins", [])
    exe     = None

    if spec.get("special") == "opera_windows":
        exe = _find_opera_windows()
        if not exe:
            print(f"[Browser] ⚠️  Opera executable not found on Windows.")
        return {"engine": engine, "exe": exe, "channel": channel}

    for b in bins:
        found = shutil.which(b)
        if found:
            exe = found
            break

    if not exe and _OS == "Darwin":
        app_names = {
            "chrome":  ["Google Chrome.app"],
            "edge":    ["Microsoft Edge.app"],
            "firefox": ["Firefox.app"],
            "opera":   ["Opera.app", "Opera GX.app"],
            "brave":   ["Brave Browser.app"],
            "vivaldi": ["Vivaldi.app"],
        }
        for app in app_names.get(name, []):
            app_dir = Path("/Applications") / app / "Contents" / "MacOS"
            if app_dir.exists():
                found_bins = list(app_dir.iterdir())
                if found_bins:
                    exe = str(found_bins[0])
                    break

    if not exe and _OS == "Windows" and not channel:
        exe = _find_exe_windows(name)

    return {"engine": engine, "exe": exe, "channel": channel}


def _detect_default_browser() -> str:
    try:
        if _OS == "Windows":
            import winreg
            k = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations"
                r"\UrlAssociations\http\UserChoice",
            )
            prog_id = winreg.QueryValueEx(k, "ProgId")[0].lower()
            winreg.CloseKey(k)
            for kw in ("edge", "firefox", "opera", "brave", "vivaldi", "chrome"):
                if kw in prog_id:
                    return kw
        elif _OS == "Darwin":
            out = subprocess.run(
                ["defaults", "read",
                 "com.apple.LaunchServices/com.apple.launchservices.secure",
                 "LSHandlers"],
                capture_output=True, text=True, timeout=5,
            ).stdout.lower()
            for kw in ("firefox", "opera", "brave", "vivaldi", "safari", "chrome", "edge"):
                if kw in out:
                    return kw
        elif _OS == "Linux":
            out = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True, text=True, timeout=5,
            ).stdout.lower()
            for kw in ("firefox", "opera", "brave", "vivaldi", "chrome", "edge"):
                if kw in out:
                    return kw
    except Exception:
        pass
    return "chrome"


_SEARCH_ENGINES: dict[str, str] = {
    "google":     "https://www.google.com/search?q=",
    "bing":       "https://www.bing.com/search?q=",
    "duckduckgo": "https://duckduckgo.com/?q=",
    "yandex":     "https://yandex.com/search/?text=",
}

_MAC_APP_NAMES: dict[str, str] = {
    "chrome":  "Google Chrome",
    "edge":    "Microsoft Edge",
    "firefox": "Firefox",
    "opera":   "Opera",
    "operagx": "Opera GX",
    "brave":   "Brave Browser",
    "vivaldi": "Vivaldi",
    "safari":  "Safari",
}

# Windows registry lookup names for browsers whose spec has no explicit binary
_WIN_EXE_HINTS: dict[str, str] = {"chrome": "chrome", "edge": "msedge"}


def _open_native(url: str, browser_name: Optional[str]) -> str:
    """
    Kullanıcının GERÇEK tarayıcısını normal şekilde açar — kendi profili,
    giriş yapılmış hesapları ve eklentileriyle. Otomasyon bağlanmaz, bu yüzden
    about:blank sekmesi veya boş profil ASLA görünmez.
    url boş ise tarayıcı URL'siz başlatılır (kendi açılış sayfası /
    oturum geri yükleme ile) — tıpkı kullanıcının kendisi açmış gibi.
    Windows / macOS / Linux üçünde de çalışır.
    """
    url = _normalize_url(url) if url and url.strip() else ""
    if url == "about:blank":
        url = ""

    name = None
    if browser_name:
        name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
    elif not url:
        # URL yok → sadece pencere açılacak; varsayılan tarayıcının exe'si gerekir
        name = _detect_default_browser()

    # Specific browser → launch its own executable, exactly like the user would.
    if name:
        if _OS == "Darwin":
            app = _MAC_APP_NAMES.get(name)
            if app:
                cmd = ["open", "-a", app] + ([url] if url else [])
                try:
                    subprocess.run(cmd, check=True, timeout=10)
                    return f"Opened in {name}: {url}" if url else f"Opened {name}."
                except Exception as e:
                    print(f"[Browser] 'open -a {app}' failed ({e}), trying binary…")

        spec = _resolve_browser(name)
        exe  = spec.get("exe") if spec else None
        if not exe and _OS == "Windows":
            if name in ("opera", "operagx"):
                exe = _find_opera_windows()
            else:
                exe = _find_exe_windows(_WIN_EXE_HINTS.get(name, name))
        if exe:
            try:
                subprocess.Popen(
                    [exe, url] if url else [exe],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return f"Opened in {name}: {url}" if url else f"Opened {name}."
            except Exception as e:
                print(f"[Browser] Native launch failed for {name}: {e}")
        print(f"[Browser] '{name}' not found — falling back to default browser.")

    if not url:
        return "Could not find a browser to open."

    # Default browser via the OS — exactly like the user clicking a link.
    try:
        if _OS == "Windows":
            os.startfile(url)                       # ShellExecute → default browser
        elif _OS == "Darwin":
            subprocess.run(["open", url], check=True, timeout=10)
        else:
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        return f"Opened in your default browser: {url}"
    except Exception:
        try:
            if webbrowser.open(url):
                return f"Opened in your default browser: {url}"
        except Exception:
            pass
        return f"Could not open a browser for: {url}"


class _BrowserSession:
    """
    Bir tarayıcı örneği için tam oturum.
    Tüm tarayıcılar launch_persistent_context ile gerçek profil üzerinde açılır.
    """

    def __init__(self, browser_name: str):
        self.browser_name = browser_name
        self._spec        = _resolve_browser(browser_name)

        self._loop:    asyncio.AbstractEventLoop | None = None
        self._thread:  threading.Thread | None          = None
        self._ready    = threading.Event()

        self._pw:      Playwright     | None = None
        self._context: BrowserContext | None = None
        self._browser: Browser        | None = None   # CDP-attached real browser
        self._page:    Page           | None = None

        # Tab-management state
        self._tab_history: list[str] = []              # recently used tab URLs
        self._protected:    set[str] = set()           # protected tab URLs

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"BrowserThread-{self.browser_name}",
        )
        self._thread.start()
        self._ready.wait(timeout=20)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._async_init())
        self._ready.set()
        self._loop.run_forever()

    async def _async_init(self):
        self._pw = await async_playwright().start()

    def run(self, coro, timeout: int = 60) -> str:
        if not self._loop:
            raise RuntimeError(f"Session for '{self.browser_name}' not started.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def close(self):
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._async_close(), self._loop).result(10)

    async def _async_close(self):
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._browser = None
        self._context = self._page = None

    # ── Backend acquisition: real Chrome via CDP, else automation profile ──

    async def _acquire(self):
        """Attach to the real browser via CDP if possible, else launch the
        automation profile. Idempotent."""
        if self._browser is not None or self._context is not None:
            return
        if self._spec and self._spec.get("engine") == "chromium":
            if await self._try_attach_cdp():
                return
        await self._launch()

    async def _try_attach_cdp(self) -> bool:
        try:
            self._browser = await self._pw.chromium.connect_over_cdp(
                f"http://127.0.0.1:{_CDP_PORT}", timeout=5_000
            )
            pages = self._all_pages()
            self._page = pages[-1] if pages else None
            print(f"[Browser] ✅ Attached to real {self.browser_name} via CDP ({len(pages)} tabs)")
            return True
        except Exception as e:
            print(f"[Browser] CDP attach failed ({e}) — using automation profile")
            self._browser = None
            return False

    def using_cdp(self) -> bool:
        return self._browser is not None

    def _all_pages(self) -> list[Page]:
        pages: list[Page] = []
        if self._browser is not None:
            for ctx in self._browser.contexts:
                pages.extend(ctx.pages)
        elif self._context is not None:
            pages.extend(self._context.pages)
        return pages

    @staticmethod
    def _domain(url: str) -> str:
        try:
            from urllib.parse import urlparse
            host = urlparse(url).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            return host
        except Exception:
            return ""

    def _push_history(self, page: Page) -> None:
        url = page.url or ""
        if not url or url == "about:blank":
            return
        if url in self._tab_history:
            self._tab_history.remove(url)
        self._tab_history.insert(0, url)
        self._tab_history = self._tab_history[:20]

    def _remove_history(self, url: str) -> None:
        if url in self._tab_history:
            self._tab_history.remove(url)

    async def _snapshot_tabs(self) -> list[dict]:
        await self._acquire()
        pages = self._all_pages()
        active_url = self._page.url if (self._page and not self._page.is_closed()) else ""
        snaps: list[dict] = []
        for i, p in enumerate(pages):
            try:
                title = (await p.title()).strip()
            except Exception:
                title = ""
            url = p.url or ""
            snaps.append({
                "index": i + 1,
                "title": title or "(untitled)",
                "url": url,
                "domain": self._domain(url),
                "active": bool(url and url == active_url),
                "protected": url in self._protected,
            })
        return snaps

    async def _find_page(self, query: str) -> Page | None:
        query = (query or "").strip()
        if not query:
            return None
        pages = self._all_pages()
        if not pages:
            return None
        if query.isdigit():
            idx = int(query)
            if 1 <= idx <= len(pages):
                return pages[idx - 1]
        q = query.lower()
        title_matches: list[Page] = []
        domain_matches: list[Page] = []
        url_matches: list[Page] = []
        for p in pages:
            try:
                title = (await p.title()).lower()
            except Exception:
                title = ""
            url = (p.url or "").lower()
            dom = self._domain(p.url or "")
            if q in title:
                title_matches.append(p)
            if q in dom:
                domain_matches.append(p)
            if q in url:
                url_matches.append(p)
        return (title_matches or domain_matches or url_matches or [None])[0]

    # ── Tab operations (async, run on the session loop) ─────────────────────

    async def list_tabs(self) -> str:
        snaps = await self._snapshot_tabs()
        if not snaps:
            return "No tabs are open."
        lines = []
        for s in snaps:
            active = " ▶" if s["active"] else ""
            prot   = " 🔒" if s["protected"] else ""
            loc = s["url"] or s["domain"] or "(no url)"
            lines.append(f"  {s['index']}. {s['title']}{active}{prot}\n     {loc}")
        return "Tabs:\n" + "\n".join(lines)

    async def switch_tab(self, query: str) -> str:
        await self._acquire()
        page = await self._find_page(query)
        if page is None:
            snaps = await self._snapshot_tabs()
            names = ", ".join(s["title"] for s in snaps)
            return (f"Could not find a tab matching '{query}'. "
                    f"Open tabs: {names}" if names else "No tabs are open.")
        try:
            await page.bring_to_front()
        except Exception:
            pass
        self._page = page
        self._push_history(page)
        title = ""
        try:
            title = await page.title()
        except Exception:
            pass
        return f"Switched to: {title or page.url} ({page.url})"

    async def close_tab_by_ref(self, query: str) -> str:
        await self._acquire()
        page = await self._find_page(query)
        if page is None:
            return f"Could not find a tab matching '{query}'."
        title = ""
        try:
            title = await page.title()
        except Exception:
            pass
        if page.url in self._protected:
            return f"'{title or page.url}' is protected. Remove protection first."
        await page.close()
        self._remove_history(page.url or "")
        if self._page is not None and self._page.is_closed():
            pages = self._all_pages()
            self._page = pages[-1] if pages else None
        return f"Closed: {title or page.url}"

    async def tab_history(self) -> str:
        if not self._tab_history:
            return "No recent tabs."
        lines = [f"  {i}. {url}" for i, url in enumerate(self._tab_history[:10], 1)]
        return "Recent tabs:\n" + "\n".join(lines)

    async def close_duplicates(self) -> str:
        await self._acquire()
        pages = self._all_pages()
        seen: dict[str, Page] = {}
        closed = 0
        for p in pages:
            url = p.url or ""
            if not url or url == "about:blank":
                continue
            if url in seen:
                if url in self._protected:
                    continue
                try:
                    await p.close()
                    closed += 1
                except Exception:
                    pass
            else:
                seen[url] = p
        if self._page is not None and self._page.is_closed():
            pages = self._all_pages()
            self._page = pages[-1] if pages else None
        return f"Closed {closed} duplicate tab(s)."

    async def set_protected(self, query: str, enable: bool) -> str:
        await self._acquire()
        page = await self._find_page(query)
        if page is None:
            return f"Could not find a tab matching '{query}'."
        url = page.url or ""
        if not url:
            return "This tab has no URL to protect."
        if enable:
            self._protected.add(url)
            return f"Protected: {url}"
        self._protected.discard(url)
        return f"Unprotected: {url}"

    async def current_tab_info(self) -> str:
        await self._acquire()
        page = self._page
        if page is None or page.is_closed():
            pages = self._all_pages()
            page = pages[-1] if pages else None
            self._page = page
        if page is None:
            return "No active tab."
        title = ""
        try:
            title = (await page.title()).strip()
        except Exception:
            pass
        url = page.url or ""
        idx = ""
        for i, p in enumerate(self._all_pages()):
            if (p.url or "") == url:
                idx = str(i + 1)
                break
        return (f"Active tab: {title or '(untitled)'}\n"
                f"URL: {url}\n"
                f"Domain: {self._domain(url)}\n"
                f"Index: {idx or '?'}")

    async def duplicate_current_tab(self) -> str:
        await self._acquire()
        page = self._page
        if page is None or page.is_closed():
            return "No active tab to duplicate."
        url = page.url or ""
        if not url:
            return "The active tab has no URL."
        return await self.new_tab(url, background=False)

    async def copy_link(self) -> str:
        await self._acquire()
        page = self._page
        if page is None or page.is_closed():
            return "No active tab."
        url = page.url or ""
        if not url:
            return "The active tab has no URL."
        try:
            import pyperclip
            pyperclip.copy(url)
            return f"Copied link: {url}"
        except Exception as e:
            return f"Could not copy link: {e}"

    async def scroll_to(self, position: str = "bottom") -> str:
        await self._acquire()
        page = self._page
        if page is None or page.is_closed():
            return "No active tab."
        try:
            if position in ("top", "start"):
                await page.evaluate("window.scrollTo(0, 0)")
            else:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            return f"Scrolled to {position}."
        except Exception as e:
            return f"Scroll error: {e}"

    async def click_first_result(self) -> str:
        await self._acquire()
        page = self._page
        if page is None or page.is_closed():
            return "No active tab."
        for sel in (
            "#search a:has(h3)",
            "#search .g a",
            "a:has(h3)",
            "main a",
        ):
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.click(timeout=5_000)
                    return "Opened the first result."
            except Exception:
                continue
        return "Could not find a result to open."

    # ── Workspaces ───────────────────────────────────────────────────────────

    async def workspace_save(self, name: str) -> str:
        await self._acquire()
        name = (name or "").strip()
        if not name:
            return "Please provide a workspace name."
        entries = []
        for p in self._all_pages():
            url = p.url or ""
            if not url or url == "about:blank":
                continue
            try:
                title = (await p.title()).strip()
            except Exception:
                title = ""
            entries.append({"title": title, "url": url})
        data = _load_workspaces()
        data[name] = entries
        _save_workspaces(data)
        return f"Saved workspace '{name}' with {len(entries)} tab(s)."

    async def workspace_restore(self, name: str) -> str:
        await self._acquire()
        name = (name or "").strip()
        data = _load_workspaces()
        entries = data.get(name)
        if not entries:
            saved = ", ".join(data) or "none"
            return f"No workspace named '{name}'. Saved: {saved}"
        ctx = self._browser.contexts[0] if self._browser is not None else self._context
        if ctx is None:
            return "No browser context available."
        first = True
        for e in entries:
            url = e.get("url", "")
            if not url:
                continue
            new = await ctx.new_page()
            try:
                await new.goto(url, wait_until="domcontentloaded", timeout=30_000)
            except PlaywrightTimeout:
                pass
            except Exception as ex:
                print(f"[Browser] workspace goto error: {ex}")
            if first:
                try:
                    await new.bring_to_front()
                except Exception:
                    pass
                self._page = new
                first = False
            self._push_history(new)
        return f"Restored workspace '{name}' ({len(entries)} tab(s))."

    async def workspace_list(self) -> str:
        data = _load_workspaces()
        if not data:
            return "No saved workspaces."
        lines = [f"  • {name} ({len(v)} tab(s))" for name, v in data.items()]
        return "Workspaces:\n" + "\n".join(lines)

    async def workspace_delete(self, name: str) -> str:
        name = (name or "").strip()
        data = _load_workspaces()
        if name not in data:
            return f"No workspace named '{name}'."
        del data[name]
        _save_workspaces(data)
        return f"Deleted workspace '{name}'."

    async def workspace_close(self, name: str) -> str:
        await self._acquire()
        name = (name or "").strip()
        data = _load_workspaces()
        entries = data.get(name)
        if not entries:
            return f"No workspace named '{name}'."
        urls = {e.get("url", "") for e in entries if e.get("url")}
        closed = 0
        for p in list(self._all_pages()):
            if (p.url or "") in urls and (p.url or "") not in self._protected:
                try:
                    await p.close()
                    closed += 1
                except Exception:
                    pass
        if self._page is not None and self._page.is_closed():
            pages = self._all_pages()
            self._page = pages[-1] if pages else None
        return f"Closed {closed} tab(s) from workspace '{name}'."

    async def _adopt_page(self) -> Page:
        """
        launch_persistent_context zaten bir başlangıç sekmesi açar.
        Yeni bir boş sekme (about:blank) açmak yerine o sekmeyi devralır —
        böylece kullanıcı fazladan boş sekme görmez.
        """
        await asyncio.sleep(0.3)
        pages = self._context.pages
        return pages[0] if pages else await self._context.new_page()

    async def _launch(self):
        """
        Tarayıcıyı gerçek kullanıcı profiliyle başlatır.
        Context zaten açıksa hiçbir şey yapmaz.
        """
        if self._context is not None:
            return

        if self._spec is None:
            raise RuntimeError(
                f"'{self.browser_name}' bu platformda ({_OS}) desteklenmiyor."
            )

        engine_name = self._spec["engine"]
        exe         = self._spec["exe"]
        channel     = self._spec["channel"]
        engine_obj  = getattr(self._pw, engine_name)

        if engine_name == "firefox":
            profile = _firefox_profile_dir() or str(
                Path.home() / ".jarvis_profiles" / "firefox"
            )
            kwargs: dict = {
                "headless":    False,
                "slow_mo":     0,
                "viewport":    None,
                "no_viewport": True,
                "timeout":     25_000,
            }
            if exe:
                kwargs["executable_path"] = exe
            try:
                self._context = await engine_obj.launch_persistent_context(profile, **kwargs)
            except Exception as e:
                print(f"[Browser] Firefox real profile failed ({e}), using JARVIS profile")
                jarvis = str(Path.home() / ".jarvis_profiles" / "firefox_jarvis")
                Path(jarvis).mkdir(parents=True, exist_ok=True)
                self._context = await engine_obj.launch_persistent_context(jarvis, **kwargs)

            self._page = await self._adopt_page()
            print(f"[Browser] ✅ Firefox launched")
            return

        if engine_name == "webkit":
            safari_profile = str(Path.home() / ".jarvis_profiles" / "safari")
            Path(safari_profile).mkdir(parents=True, exist_ok=True)
            kwargs = {
                "headless":    False,
                "slow_mo":     0,
                "viewport":    None,
                "no_viewport": True,
                "timeout":     25_000,
            }
            self._context = await engine_obj.launch_persistent_context(safari_profile, **kwargs)
            self._page = await self._adopt_page()
            print(f"[Browser] ✅ Safari launched")
            return

        profile = _real_profile_dir(self.browser_name)

        kwargs = {
            "headless":    False,
            "slow_mo":     0,
            "viewport":    None,
            "no_viewport": True,
            "timeout":     25_000,
            "args": [
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--disable-default-apps",
                "--no-default-browser-check",
            ],
        }

        if exe:
            kwargs["executable_path"] = exe
        elif channel:
            kwargs["channel"] = channel

        label = (
            f"{self.browser_name}"
            + (f"/{channel}" if channel else "")
            + (f" @ {exe}" if exe else "")
        )

        try:
            self._context = await engine_obj.launch_persistent_context(profile, **kwargs)
            self._page = await self._adopt_page()
            print(f"[Browser] ✅ Launched [{label}] profile={profile}")
            return
        except Exception as e:
            print(f"[Browser] ⚠️  Real profile failed for {label}: {e}")

        # Gerçek profil açılamadı (tarayıcı zaten açık / kilitli profil / yeni
        # Chrome sürümleri otomasyonla gerçek profili engelliyor). Kalıcı
        # JARVIS otomasyon profiline geçilir — buraya bir kez giriş yapılan
        # hesaplar sonraki oturumlarda da açık kalır.
        jarvis_profile = str(Path.home() / ".jarvis_profiles" / self.browser_name)
        Path(jarvis_profile).mkdir(parents=True, exist_ok=True)
        print(f"[Browser] Retrying with JARVIS profile: {jarvis_profile}")

        try:
            self._context = await engine_obj.launch_persistent_context(jarvis_profile, **kwargs)
            self._page = await self._adopt_page()
            print(f"[Browser] ✅ Launched [{label}] with JARVIS profile "
                  f"(sign-ins persist across sessions)")
        except Exception as e2:
            raise RuntimeError(f"Could not launch {self.browser_name}: {e2}") from e2


    async def _get_page(self) -> Page:
        await self._acquire()
        if self._browser is not None:
            # CDP mode: reuse the last active tab, or pick the last open one.
            if self._page is None or self._page.is_closed():
                pages = self._all_pages()
                self._page = pages[-1] if pages else None
            if self._page is None:
                ctx = self._browser.contexts[0] if self._browser.contexts else None
                if ctx is not None:
                    self._page = await ctx.new_page()
            return self._page
        # Automation fallback (persistent context)
        if self._page is None or self._page.is_closed():
            self._page = await self._context.new_page()
            await asyncio.sleep(0.2)
        return self._page

    async def go_to(self, url: str) -> str:

        url      = _normalize_url(url)
        page     = await self._get_page()
        prev_url = page.url

        async def _do_goto(p: Page) -> str:
            """Attempt navigation and return the resulting URL (may still be blank)."""
            try:
                await p.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await asyncio.sleep(0.3)
            except PlaywrightTimeout:
                pass   # page may have partially loaded — check URL below
            except Exception as e:
                print(f"[Browser] goto exception (non-fatal): {e}")
            return p.url

        result_url = await _do_goto(page)

        if result_url in ("about:blank", "", None, prev_url) and prev_url in ("about:blank", "", None):
            print(f"[Browser] Still blank after goto — retrying on new tab: {url}")
            try:
                new_page   = await self._context.new_page()
                self._page = new_page
                result_url = await _do_goto(new_page)
            except Exception as e:
                print(f"[Browser] New-tab retry failed: {e}")

        if result_url and result_url not in ("about:blank", "", None):
            return f"Opened: {result_url}"
        return f"Could not open: {url}"

    async def search(self, query: str, engine: str = "google") -> str:
        base = _SEARCH_ENGINES.get(engine.lower(), _SEARCH_ENGINES["google"])
        return await self.go_to(base + query.replace(" ", "+"))

    async def click(self, selector: str = None, text: str = None) -> str:
        page = await self._get_page()
        try:
            if text:
                await page.get_by_text(text, exact=False).first.click(timeout=8_000)
                return f"Clicked text: '{text}'"
            if selector:
                await page.click(selector, timeout=8_000)
                return f"Clicked selector: {selector}"
            return "No selector or text provided."
        except PlaywrightTimeout:
            return "Element not found (timeout)."
        except Exception as e:
            return f"Click error: {e}"

    async def type_text(self, selector: str = None, text: str = "",
                        clear_first: bool = True) -> str:
        page = await self._get_page()
        try:
            el = page.locator(selector).first if selector else page.locator(":focus")
            if clear_first:
                await el.clear()
            await el.type(text, delay=50)
            return "Text typed."
        except Exception as e:
            return f"Type error: {e}"

    async def scroll(self, direction: str = "down", amount: int = 500) -> str:
        page = await self._get_page()
        try:
            y = amount if direction == "down" else -amount
            await page.mouse.wheel(0, y)
            return f"Scrolled {direction}."
        except Exception as e:
            return f"Scroll error: {e}"

    async def press(self, key: str) -> str:
        page = await self._get_page()
        try:
            await page.keyboard.press(key)
            return f"Pressed: {key}"
        except Exception as e:
            return f"Key error: {e}"

    async def get_text(self) -> str:
        page = await self._get_page()
        try:
            text = await page.inner_text("body")
            return text[:4_000]
        except Exception as e:
            return f"Could not get page text: {e}"

    async def get_url(self) -> str:
        page = await self._get_page()
        return page.url

    async def fill_form(self, fields: dict) -> str:
        page    = await self._get_page()
        results = []
        for selector, value in fields.items():
            try:
                el = page.locator(selector).first
                await el.clear()
                await el.type(str(value), delay=40)
                results.append(f"✓ {selector}")
            except Exception as e:
                results.append(f"✗ {selector}: {e}")
        return "Form filled: " + ", ".join(results)

    async def smart_click(self, description: str) -> str:
        page = await self._get_page()
        for role in ("button", "link", "searchbox", "textbox", "menuitem", "tab"):
            try:
                loc = page.get_by_role(role, name=description)
                if await loc.count() > 0:
                    await loc.first.click(timeout=5_000)
                    return f"Clicked ({role}): '{description}'"
            except Exception:
                pass
        for attempt in (
            lambda: page.get_by_text(description, exact=False).first.click(timeout=5_000),
            lambda: page.get_by_placeholder(description, exact=False).first.click(timeout=5_000),
            lambda: page.locator(
                f'[alt*="{description}" i],[title*="{description}" i],'
                f'[aria-label*="{description}" i]'
            ).first.click(timeout=5_000),
        ):
            try:
                await attempt()
                return f"Clicked: '{description}'"
            except Exception:
                pass
        return f"Could not find element: '{description}'"

    async def smart_type(self, description: str, text: str) -> str:
        page = await self._get_page()
        candidates = [
            ("placeholder", page.get_by_placeholder(description, exact=False)),
            ("label",       page.get_by_label(description, exact=False)),
            ("role",        page.get_by_role("textbox", name=description)),
            ("searchbox",   page.get_by_role("searchbox")),
            ("combobox",    page.get_by_role("combobox", name=description)),
        ]
        for method, loc in candidates:
            try:
                el = loc.first
                if await el.count() == 0:
                    continue
                await el.clear()
                await el.type(text, delay=50)
                return f"Typed into ({method}): '{description}'"
            except Exception:
                continue
        return f"Could not find input: '{description}'"

    async def new_tab(self, url: str = "", background: bool = False) -> str:
        await self._acquire()
        ctx = None
        if self._browser is not None:
            ctx = self._browser.contexts[0] if self._browser.contexts else None
        elif self._context is not None:
            ctx = self._context
        if ctx is None:
            return "No browser context available."
        new = await ctx.new_page()
        if url:
            try:
                await new.goto(_normalize_url(url), wait_until="domcontentloaded", timeout=30_000)
            except PlaywrightTimeout:
                pass
            except Exception as e:
                print(f"[Browser] new_tab navigation error: {e}")
        if not background:
            try:
                await new.bring_to_front()
            except Exception:
                pass
            self._page = new
        self._push_history(new)
        return f"Opened new tab: {new.url or url or 'about:blank'}"

    async def close_tab(self) -> str:
        page = self._page
        if page and not page.is_closed():
            ctx   = page.context
            await page.close()
            pages = ctx.pages
            self._page = pages[-1] if pages else None
            return "Tab closed."
        return "No active tab to close."

    async def screenshot(self, path: str = None) -> str:
        page = await self._get_page()
        try:
            save_path = path or str(Path.home() / "Desktop" / "jarvis_screenshot.png")
            await page.screenshot(path=save_path, full_page=False)
            return f"Screenshot saved: {save_path}"
        except Exception as e:
            return f"Screenshot error: {e}"

    async def back(self) -> str:
        page = await self._get_page()
        try:
            await page.go_back(timeout=10_000)
            return f"Navigated back: {page.url}"
        except Exception as e:
            return f"Back error: {e}"

    async def forward(self) -> str:
        page = await self._get_page()
        try:
            await page.go_forward(timeout=10_000)
            return f"Navigated forward: {page.url}"
        except Exception as e:
            return f"Forward error: {e}"

    async def reload(self) -> str:
        page = await self._get_page()
        try:
            await page.reload(timeout=15_000)
            return f"Page reloaded: {page.url}"
        except Exception as e:
            return f"Reload error: {e}"

    async def close_browser(self) -> str:
        await self._async_close()
        return f"{self.browser_name} closed."

class _SessionRegistry:
    """Tüm aktif tarayıcı oturumlarını yönetir."""

    def __init__(self):
        self._sessions:        dict[str, _BrowserSession] = {}
        self._active_browser:  str                        = ""
        self._lock             = threading.Lock()
        self._last_native_url: str                        = ""

    def has(self, browser_name: str | None = None) -> bool:
        """Bu tarayıcı için (veya hiç) aktif bir otomasyon oturumu var mı?"""
        with self._lock:
            if not browser_name:
                return bool(self._sessions)
            name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
            return name in self._sessions

    def note_native_url(self, url: str) -> None:
        self._last_native_url = url

    def pop_native_url(self) -> str:
        """Son native açılan URL'yi bir kez döndürür (tekrarı önlemek için tüketilir)."""
        url, self._last_native_url = self._last_native_url, ""
        return url

    def _get_or_create(self, browser_name: str) -> _BrowserSession:
        with self._lock:
            if browser_name not in self._sessions:
                sess = _BrowserSession(browser_name)
                sess.start()
                self._sessions[browser_name] = sess
                print(f"[Registry] New session: {browser_name}")
            return self._sessions[browser_name]

    def get(self, browser_name: str | None = None) -> _BrowserSession:
        if not browser_name:
            browser_name = self._active_browser or _detect_default_browser()
        browser_name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
        sess = self._get_or_create(browser_name)
        self._active_browser = browser_name
        return sess

    def switch(self, browser_name: str) -> str:
        browser_name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
        self._get_or_create(browser_name)
        self._active_browser = browser_name
        return f"Active browser → {browser_name}"

    def close_one(self, browser_name: str) -> str:
        with self._lock:
            sess = self._sessions.pop(browser_name, None)
        if sess:
            sess.close()
            if self._active_browser == browser_name:
                self._active_browser = ""
            return f"{browser_name} closed."
        return f"No active session for: {browser_name}"

    def close_all(self) -> str:
        with self._lock:
            names    = list(self._sessions.keys())
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._active_browser = ""
        for s in sessions:
            try:
                s.close()
            except Exception:
                pass
        return "All browsers closed: " + (", ".join(names) if names else "none")

    def list_sessions(self) -> str:
        with self._lock:
            if not self._sessions:
                return "No active browser sessions."
            lines = []
            for name in self._sessions:
                marker = " ◀ active" if name == self._active_browser else ""
                lines.append(f"  • {name}{marker}")
            return "Open browsers:\n" + "\n".join(lines)


_registry = _SessionRegistry()

def browser_control(
    parameters:    dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params  = parameters or {}
    action  = params.get("action", "").lower().strip()
    browser = params.get("browser", "").lower().strip() or None
    result  = "Unknown action."

    # Defensive routing: 'close' that names a tab means close ONE tab, never
    # the whole browser.
    if action == "close" and (
        params.get("tab_name") or params.get("title")
        or params.get("text") or params.get("index") is not None
    ):
        action = "close_tab"

    if action == "switch":
        target = browser or params.get("target", "").lower().strip()
        result = _registry.switch(target) if target else "Please specify a browser."
        _log(player, result)
        return result

    if action == "list_browsers":
        result = _registry.list_sessions()
        _log(player, result)
        return result

    if action == "close_all":
        result = _registry.close_all()
        _log(player, result)
        return result

    if action == "close":
        target = browser or _registry._active_browser
        result = _registry.close_one(target) if target else "No browser specified."
        _log(player, result)
        return result

    if action == "cdp_launch":
        result = launch_chrome_control_mode()
        _log(player, result)
        return result

    # ── Close a specific tab by name/index ───────────────────────────────────
    # Closes ONE tab only — never the whole browser.
    if action == "close_tab":
        tab_name = (
            params.get("tab_name")
            or params.get("title")
            or params.get("text")
            or params.get("name")
            or params.get("value")
            or ""
        ).strip()
        index = params.get("index")

        if tab_name:
            # 1) Existing CDP session → close by title/domain/url (any browser).
            sess = _registry.get(browser) if _registry.has(browser) else None
            if sess is not None and sess.using_cdp():
                try:
                    result = sess.run(sess.close_tab_by_ref(tab_name))
                    _log(player, result)
                    return result
                except Exception as e:
                    print(f"[Browser] CDP close_tab failed, trying UI Automation: {e}")

            # 2) UI Automation on the user's real Chromium browser — no new window.
            result = close_chrome_tab_by_name(tab_name, browser or "chrome")
            if result.startswith("Closed the"):
                _log(player, result)
                return result

            # 3) Existing session fallback (never opens a new browser window).
            if sess is not None:
                try:
                    result = sess.run(sess.close_tab_by_ref(tab_name))
                except Exception as e:
                    result = f"Could not close tab: {e}"
            _log(player, result)
            return result

        if index is not None:
            try:
                sess = _registry.get(browser)
                result = sess.run(sess.close_tab_by_ref(str(index)))
            except Exception as e:
                result = f"Could not close tab: {e}"
            _log(player, result)
            return result
        # no name/index → fall through to the interactive path (close active tab)

    # ── Tab management (list / switch / history / duplicates / protect) ─────
    # These use the session, which attaches to the real Chrome via CDP when
    # available and otherwise falls back to the automation profile.
    if action in ("list_tabs", "switch_tab", "tab_history", "close_duplicates",
                  "protect", "unprotect", "current_tab", "open_in_new_tab",
                  "workspace", "copy_link", "scroll_to", "click_first_result"):
        try:
            sess = _registry.get(browser)
        except Exception as e:
            result = f"Could not start browser session: {e}"
            _log(player, result)
            return result
        try:
            if action == "list_tabs":
                result = sess.run(sess.list_tabs())
            elif action == "switch_tab":
                query = str(
                    params.get("tab_name") or params.get("title")
                    or params.get("text") or params.get("name")
                    or params.get("index") or ""
                ).strip()
                result = sess.run(sess.switch_tab(query))
            elif action == "tab_history":
                result = sess.run(sess.tab_history())
            elif action == "close_duplicates":
                result = sess.run(sess.close_duplicates())
            elif action == "current_tab":
                result = sess.run(sess.current_tab_info())
            elif action == "open_in_new_tab":
                result = sess.run(sess.duplicate_current_tab())
            elif action == "copy_link":
                result = sess.run(sess.copy_link())
            elif action == "scroll_to":
                result = sess.run(sess.scroll_to(
                    (params.get("position") or params.get("direction") or "bottom").lower()))
            elif action == "click_first_result":
                result = sess.run(sess.click_first_result())
            elif action == "workspace":
                cmd = (params.get("command") or "").lower().strip()
                name = str(params.get("name") or params.get("value") or "").strip()
                if cmd == "save":
                    result = sess.run(sess.workspace_save(name))
                elif cmd == "restore":
                    result = sess.run(sess.workspace_restore(name))
                elif cmd == "list":
                    result = sess.run(sess.workspace_list())
                elif cmd == "delete":
                    result = sess.run(sess.workspace_delete(name))
                elif cmd == "close":
                    result = sess.run(sess.workspace_close(name))
                else:
                    result = "Specify command: save | restore | list | delete | close"
            else:  # protect / unprotect
                query = str(
                    params.get("tab_name") or params.get("title")
                    or params.get("text") or params.get("name") or ""
                ).strip()
                result = sess.run(sess.set_protected(query, action == "protect"))
        except concurrent.futures.TimeoutError:
            result = f"Browser action '{action}' timed out (60s)."
        except Exception as e:
            result = f"Browser error ({action}): {e}"
        _log(player, result)
        return result

    # ── Gezinme HER ZAMAN native ─────────────────────────────────────────────
    # go_to / search / new_tab siteyi kullanıcının kendi tarayıcısında açar —
    # kendi profili, giriş yapılmış hesapları ve açılış sayfasıyla; tıpkı
    # kullanıcının kendisi açmış gibi. about:blank'li kontrollü pencere burada
    # asla açılmaz. Tek istisna: hâlihazırda süren bir otomasyon akışı varsa
    # gezinme o pencerede devam eder (çok adımlı görevler bölünmesin diye).
    if action in ("go_to", "search", "new_tab"):
        if _registry.has(browser):
            sess = _registry.get(browser)
            try:
                if action == "search":
                    result = sess.run(sess.search(params.get("query", ""),
                                                  params.get("engine", "google")))
                elif action == "new_tab":
                    result = sess.run(sess.new_tab(
                        params.get("url", ""),
                        bool(params.get("background", False))))
                else:
                    result = sess.run(sess.go_to(params.get("url", "")))
            except concurrent.futures.TimeoutError:
                result = f"Browser action '{action}' timed out (60s)."
            except Exception as e:
                result = f"Browser error ({action}): {e}"
            _log(player, result)
            return result

        if action == "search":
            base    = _SEARCH_ENGINES.get(params.get("engine", "google").lower(),
                                          _SEARCH_ENGINES["google"])
            nav_url = base + params.get("query", "").replace(" ", "+")
        else:
            nav_url = params.get("url", "").strip()

        # If the site is already open in a tab/window, switch to it instead of
        # opening yet another one. Chrome tab switch handles background tabs;
        # the window-title fallback covers the active tab and other browsers.
        if action == "go_to" and nav_url:
            kw = _site_keyword(nav_url)
            if kw:
                if (not browser or browser == "chrome") and switch_chrome_tab(kw):
                    result = f"Switched to the existing {kw} tab."
                    _log(player, result)
                    return result
                if _focus_existing_window(kw):
                    result = f"Focused the existing {kw} window."
                    _log(player, result)
                    return result

        result = _open_native(nav_url, browser)
        if result.startswith("Opened") and nav_url:
            _registry.note_native_url(_normalize_url(nav_url))
        _log(player, result)
        return result

    # ── Etkileşimli aksiyonlar (tıklama/yazma/okuma…) ────────────────────────
    # Bunlar fiziksel olarak kontrol edilebilir bir tarayıcı gerektirir;
    # yalnızca burada otomasyon penceresi açılır ve açılır açılmaz kullanıcının
    # son gezindiği sayfaya gider — boş sayfada beklemez.
    try:
        sess = _registry.get(browser)
    except Exception as e:
        result = f"Could not start browser session: {e}"
        _log(player, result)
        return result

    try:
        last = _registry.pop_native_url()
        if last:
            try:
                sess.run(sess.go_to(last))
            except Exception as e:
                print(f"[Browser] Could not resume last page ({last}): {e}")

        if action == "click":
            result = sess.run(sess.click(params.get("selector"), params.get("text")))
        elif action == "type":
            result = sess.run(sess.type_text(
                params.get("selector"), params.get("text", ""), params.get("clear_first", True)))
        elif action == "scroll":
            result = sess.run(sess.scroll(params.get("direction", "down"), int(params.get("amount", 500))))
        elif action == "fill_form":
            result = sess.run(sess.fill_form(params.get("fields", {})))
        elif action == "smart_click":
            result = sess.run(sess.smart_click(params.get("description", "")))
        elif action == "smart_type":
            result = sess.run(sess.smart_type(params.get("description", ""), params.get("text", "")))
        elif action == "get_text":
            result = sess.run(sess.get_text())
        elif action == "get_url":
            result = sess.run(sess.get_url())
        elif action == "press":
            result = sess.run(sess.press(params.get("key", "Enter")))
        elif action == "close_tab":
            result = sess.run(sess.close_tab())
        elif action == "screenshot":
            result = sess.run(sess.screenshot(params.get("path")))
        elif action == "back":
            result = sess.run(sess.back())
        elif action == "forward":
            result = sess.run(sess.forward())
        elif action == "reload":
            result = sess.run(sess.reload())
        else:
            result = f"Unknown browser action: '{action}'"

    except concurrent.futures.TimeoutError:
        result = f"Browser action '{action}' timed out (60s)."
    except Exception as e:
        result = f"Browser error ({action}): {e}"

    _log(player, result)
    return result


def _log(player, text: str):
    short = str(text)[:80]
    print(f"[Browser] {short}")
    if player:
        player.write_log(f"[browser] {short[:60]}")