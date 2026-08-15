#computer_settings.py
import json
import os
import re
import sys
import time
import subprocess
import platform
from pathlib import Path

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

from actions.open_app import _normalize, _APP_ALIASES

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"

if _OS == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _get_api_key() -> str:
    path = _get_base_dir() / "config" / "api_keys.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]

def _get_macos_wifi_interface() -> str:
    try:
        result = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.splitlines()
        for i, line in enumerate(lines):
            if "Wi-Fi" in line or "AirPort" in line:
                for j in range(i, min(i + 4, len(lines))):
                    if lines[j].startswith("Device:"):
                        return lines[j].split(":", 1)[1].strip()
    except Exception:
        pass
    return "en0" 

def _endpoint_volume():
    """Return the master IAudioEndpointVolume for the default render device."""
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities.GetSpeakers().EndpointVolume

def volume_up():
    if _OS == "Windows":
        try:
            v = _endpoint_volume()
            v.SetMasterVolumeLevelScalar(min(1.0, v.GetMasterVolumeLevelScalar() + 0.1), None)
        except Exception as e:
            print(f"[Settings] volume_up via pycaw failed: {e}")
            pyautogui.press("volumeup")
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            "set volume output volume (output volume of (get volume settings) + 10)"],
            capture_output=True)
    else:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"],
            capture_output=True)

def volume_down():
    if _OS == "Windows":
        try:
            v = _endpoint_volume()
            v.SetMasterVolumeLevelScalar(max(0.0, v.GetMasterVolumeLevelScalar() - 0.1), None)
        except Exception as e:
            print(f"[Settings] volume_down via pycaw failed: {e}")
            pyautogui.press("volumedown")
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            "set volume output volume (output volume of (get volume settings) - 10)"],
            capture_output=True)
    else:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"],
            capture_output=True)

def volume_mute():
    if _OS == "Windows":
        try:
            v = _endpoint_volume()
            v.SetMute(not v.GetMute(), None)
        except Exception as e:
            print(f"[Settings] volume_mute via pycaw failed: {e}")
            pyautogui.press("volumemute")
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e", "set volume with output muted"],
            capture_output=True)
    else:
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
            capture_output=True)

def volume_set(value: int):
    value = max(0, min(100, int(value)))
    if _OS == "Windows":
        try:
            _endpoint_volume().SetMasterVolumeLevelScalar(value / 100.0, None)
            return
        except Exception as e:
            print(f"[Settings] volume_set via pycaw failed: {e}")
            raise
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e", f"set volume output volume {value}"],
            capture_output=True)
        return
    else:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"],
            capture_output=True)
        return


# ── Per-application volume (session volume) ──────────────────────────────────
# The volume_up/down/set/mute functions above change the WINDOWS master volume.
# These helpers instead target ONE app's audio session (e.g. Spotify, or the
# browser playing the Spotify web player) via the Windows Core Audio session API,
# leaving the master volume and every other app untouched.

def _matching_audio_session(stems) -> object | None:
    """Return the first audio session whose process name matches ``stems``."""
    if _OS != "Windows":
        return None
    try:
        from pycaw.pycaw import AudioUtilities
        for s in AudioUtilities.GetAllSessions():
            proc = getattr(s, "Process", None)
            if proc is None:
                continue
            try:
                pstem = (proc.name() or "").lower().rsplit(".", 1)[0]
            except Exception:
                continue
            if any(st == pstem or st in pstem for st in stems):
                return s
    except Exception as e:
        print(f"[Settings] _matching_audio_session failed: {e}")
    return None


def get_app_volume(stems) -> float | None:
    """Current volume (0.0-1.0) of the first matching app session, or None."""
    s = _matching_audio_session(stems)
    if s is None or getattr(s, "SimpleAudioVolume", None) is None:
        return None
    try:
        return float(s.SimpleAudioVolume.GetMasterVolume())
    except Exception as e:
        print(f"[Settings] get_app_volume failed: {e}")
        return None


def set_app_volume(stems, value: float) -> bool:
    """Set the volume (0.0-1.0) of the first matching app session."""
    s = _matching_audio_session(stems)
    if s is None or getattr(s, "SimpleAudioVolume", None) is None:
        return False
    try:
        s.SimpleAudioVolume.SetMasterVolume(max(0.0, min(1.0, float(value))), None)
        return True
    except Exception as e:
        print(f"[Settings] set_app_volume failed: {e}")
        return False


def toggle_app_mute(stems) -> bool | None:
    """Toggle mute on the first matching app session. Returns the new mute state
    (True=muted, False=unmuted) or None if no session was found."""
    s = _matching_audio_session(stems)
    if s is None or getattr(s, "SimpleAudioVolume", None) is None:
        return None
    try:
        new = not bool(s.SimpleAudioVolume.GetMute())
        s.SimpleAudioVolume.SetMute(new, None)
        return new
    except Exception as e:
        print(f"[Settings] toggle_app_mute failed: {e}")
        return None


def brightness_up():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to key code 144'],
            capture_output=True)
    elif _OS == "Linux":
        if subprocess.run(["which", "brightnessctl"],
                capture_output=True).returncode == 0:
            subprocess.run(["brightnessctl", "set", "+10%"], capture_output=True)
        else:
            subprocess.run(
                'xrandr --output $(xrandr | grep " connected" | head -1 | cut -d " " -f1)'
                ' --brightness $(python3 -c "import subprocess; '
                'b=float(subprocess.check_output([\"xrandr\",\"--verbose\"]).decode()'
                '.split(\"Brightness:\")[1].split()[0]); print(min(1.0,b+0.1))")',
                shell=True, capture_output=True
            )
    else:
        try:
            subprocess.run(
                ["powershell", "-Command",
                 "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods)"
                 ".WmiSetBrightness(1, [math]::Min(100, "
                 "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness).CurrentBrightness + 10))"],
                capture_output=True, timeout=5, **_WIN_HIDE
            )
        except Exception as e:
            print(f"[Settings] Brightness up failed on Windows: {e}")

def brightness_down():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to key code 145'],
            capture_output=True)
    elif _OS == "Linux":
        if subprocess.run(["which", "brightnessctl"],
                capture_output=True).returncode == 0:
            subprocess.run(["brightnessctl", "set", "10%-"], capture_output=True)
        else:
            subprocess.run(
                'xrandr --output $(xrandr | grep " connected" | head -1 | cut -d " " -f1)'
                ' --brightness $(python3 -c "import subprocess; '
                'b=float(subprocess.check_output([\"xrandr\",\"--verbose\"]).decode()'
                '.split(\"Brightness:\")[1].split()[0]); print(max(0.1,b-0.1))")',
                shell=True, capture_output=True
            )
    else:
        try:
            subprocess.run(
                ["powershell", "-Command",
                 "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods)"
                 ".WmiSetBrightness(1, [math]::Max(0, "
                 "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness).CurrentBrightness - 10))"],
                capture_output=True, timeout=5, **_WIN_HIDE
            )
        except Exception as e:
            print(f"[Settings] Brightness down failed on Windows: {e}")

def _extract_app_name_from_description(description: str) -> str:
    desc = description.lower()
    for alias in sorted(_APP_ALIASES, key=len, reverse=True):
        if alias in desc:
            return _normalize(alias)
    return ""


_GENERIC_GAME_TERMS = {
    "game", "the game", "this game", "current game", "my game",
    "игра", "игру", "эту игру", "эта игра", "oyun",
}

_GAME_EXE_ALIASES: dict[str, list[str]] = {
    "counter-strike 2": ["cs2"],
    "counter strike 2": ["cs2"],
    "cs2": ["cs2"],
    "csgo": ["cs2"],
    "dota 2": ["dota2"],
    "dota2": ["dota2"],
    "pubg": ["tslgame"],
    "pubg battlegrounds": ["tslgame"],
    "gta v": ["gta5"],
    "gta5": ["gta5"],
    "grand theft auto v": ["gta5"],
    "rust": ["rustclient"],
    "valheim": ["valheim"],
    "cyberpunk 2077": ["cyberpunk2077", "cyberpunk2077.exe"],
    "cyberpunk": ["cyberpunk2077"],
    "elden ring": ["eldenring"],
    "apex legends": ["r5apex"],
    "apex": ["r5apex"],
    "fortnite": ["fortniteclient-win64-shipping"],
    "rocket league": ["rocketleague"],
    "warframe": ["warframe.x64"],
    "destiny 2": ["destiny2"],
    "team fortress 2": ["hl2"],
    "tf2": ["hl2"],
    "left 4 dead 2": ["left4dead2"],
    "l4d2": ["left4dead2"],
    "lost ark": ["lostark"],
    "path of exile": ["pathofexile"],
    "poe": ["pathofexile"],
    "war thunder": ["aces"],
    "minecraft": ["minecraft", "javaw"],
    "palworld": ["palworld-win64-shipping"],
    "helldivers 2": ["helldivers2"],
    "baldur's gate 3": ["bg3", "bg3_dx11"],
    "baldurs gate 3": ["bg3", "bg3_dx11"],
}

_SYSTEM_PROTECTED_EXES = {
    "explorer", "csrss", "winlogon", "dwm", "python", "pythonw",
    "cmd", "powershell", "conhost", "cursor", "code", "system",
    "registry", "smss", "services", "lsass", "svchost",
}

_BROWSER_EXES = {
    "chrome", "msedge", "firefox", "opera", "brave", "vivaldi",
    "iexplore", "chromium",
}


def _is_browser_pid(pid: int) -> bool:
    """True if the given PID belongs to a web browser process."""
    if not _PSUTIL or not pid:
        return False
    try:
        return _process_stem(psutil.Process(pid).name()) in _BROWSER_EXES
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def _is_generic_game_request(app_name: str | None) -> bool:
    if not app_name:
        return True
    stem = app_name.lower().strip()
    return stem in _GENERIC_GAME_TERMS


def _resolve_game_exe_terms(app_name: str) -> list[str]:
    name_lower = app_name.lower().strip()
    exes: list[str] = []
    for key, stems in _GAME_EXE_ALIASES.items():
        if key in name_lower or name_lower in key:
            exes.extend(stems)
    for term in _process_match_terms(app_name):
        if term.endswith(".exe"):
            term = term[:-4]
        if term and term not in exes:
            exes.append(term)
    return list(dict.fromkeys(exes))


def _get_foreground_pid_windows() -> int | None:
    if _OS != "Windows":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) or None
    except Exception:
        return None


def _get_pids_by_window_title(substring: str) -> list[int]:
    if _OS != "Windows" or not substring:
        return []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        needle = substring.lower()
        pids: list[int] = []

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            if needle in buff.value.lower():
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value:
                    pids.append(int(pid.value))
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        return list(dict.fromkeys(pids))
    except Exception:
        return []


def _process_stem(name: str) -> str:
    return (name or "").lower().strip().removesuffix(".exe")


def _is_protected_process(proc) -> bool:
    protected = _protected_pids()
    try:
        if proc.pid in protected:
            return True
        if getattr(proc, "info", None):
            name = proc.info.get("name")
        else:
            name = proc.name()
        stem = _process_stem(name)
        return stem in _SYSTEM_PROTECTED_EXES
    except Exception:
        return True


def _processes_running(exe_stems: set[str], pids: set[int] | None = None) -> bool:
    if not _PSUTIL:
        return bool(exe_stems or pids)
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if pids and proc.info["pid"] in pids:
                    return True
                stem = _process_stem(proc.info["name"])
                if exe_stems and stem in exe_stems:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return False


def _kill_pids(pids: list[int]) -> bool:
    if not pids:
        return False

    killed_any = False
    target_pids = set(pids)

    if _PSUTIL:
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                if _is_protected_process(proc):
                    target_pids.discard(pid)
                    continue
                proc.kill()
                killed_any = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                target_pids.discard(pid)
                killed_any = True
            except Exception:
                pass
        if killed_any:
            time.sleep(0.5)
            return not _processes_running(set(), target_pids)

    if _OS == "Windows":
        for pid in pids:
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/F", "/T"],
                capture_output=True, timeout=8, **_WIN_HIDE,
            )
            if result.returncode == 0:
                killed_any = True
        if killed_any:
            time.sleep(0.5)
            return not _processes_running(set(), target_pids)

    return False


def _kill_exe_stems(exe_stems: list[str]) -> bool:
    stems = [_process_stem(s) for s in exe_stems if s]
    stems = [s for s in dict.fromkeys(stems) if s not in _SYSTEM_PROTECTED_EXES]
    if not stems:
        return False

    killed_any = False

    if _PSUTIL:
        targets = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if _is_protected_process(proc):
                    continue
                stem = _process_stem(proc.info["name"])
                if any(stem == s or s in stem for s in stems):
                    targets.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        for proc in targets:
            try:
                proc.kill()
                killed_any = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if targets:
            time.sleep(0.5)
            return not _processes_running(set(stems))

    if _OS == "Windows":
        for stem in stems:
            result = subprocess.run(
                ["taskkill", "/IM", f"{stem}.exe", "/F", "/T"],
                capture_output=True, timeout=8, **_WIN_HIDE,
            )
            if result.returncode == 0:
                killed_any = True
        if killed_any:
            time.sleep(0.5)
            return not _processes_running(set(stems))

    return False


def _close_foreground_app() -> bool:
    pid = _get_foreground_pid_windows()
    if not pid or not _PSUTIL:
        return False
    try:
        proc = psutil.Process(pid)
        if _is_protected_process(proc):
            return False
        stem = _process_stem(proc.name())
        if stem in _SYSTEM_PROTECTED_EXES:
            return False
        return _kill_pids([pid])
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def _protected_pids() -> set[int]:
    protected = {os.getpid()}
    if not _PSUTIL:
        return protected
    try:
        for child in psutil.Process(os.getpid()).children(recursive=True):
            protected.add(child.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return protected


def _process_match_terms(app_name: str) -> list[str]:
    terms: set[str] = set()
    for candidate in (app_name, _normalize(app_name)):
        stem = candidate.lower().strip().removesuffix(".exe")
        if not stem:
            continue
        terms.add(stem)
        terms.add(stem.replace(" ", ""))
        terms.add(stem.replace(" ", "-"))
    return sorted(terms, key=len, reverse=True)


def _focus_app_window(title: str) -> bool:
    if not title:
        return False
    if _OS == "Windows":
        try:
            script = f'(New-Object -ComObject WScript.Shell).AppActivate("{title}")'
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, timeout=5, **_WIN_HIDE,
            )
            return result.returncode == 0
        except Exception:
            return False
    if _OS == "Darwin":
        script = (
            f'tell application "System Events" to '
            f'set frontmost of (first process whose name contains "{title}") to true'
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False
    try:
        result = subprocess.run(
            ["wmctrl", "-a", title],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _close_app_by_name(app_name: str) -> bool:
    if _is_generic_game_request(app_name):
        return _close_foreground_app()

    game_exes = _resolve_game_exe_terms(app_name)
    if game_exes and _kill_exe_stems(game_exes):
        return True

    # 1) Match by process name first — the most specific signal. This avoids
    #    killing a browser whose active tab title merely contains the app name
    #    (e.g. "Telegram" matching the "Telegram Web" Chrome tab).
    terms = _process_match_terms(app_name)
    if terms:
        matched: list = []
        if _PSUTIL:
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if _is_protected_process(proc):
                        continue
                    pname = _process_stem(proc.info["name"])
                    if any(term == pname or term in pname for term in terms):
                        matched.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        if matched:
            pids = [p.pid for p in matched]
            if _kill_pids(pids):
                return True

        if _OS == "Windows":
            for term in terms:
                if term in _SYSTEM_PROTECTED_EXES:
                    continue
                result = subprocess.run(
                    ["taskkill", "/IM", f"{term}.exe", "/F", "/T"],
                    capture_output=True, timeout=8, **_WIN_HIDE,
                )
                if result.returncode == 0:
                    time.sleep(0.5)
                    if not _processes_running({term}):
                        return True

    # 2) Fall back to matching by window title — but never touch browsers,
    #    whose window title is just the active tab and can match any app name.
    title_pids = [
        pid for pid in _get_pids_by_window_title(app_name)
        if not _is_browser_pid(pid)
    ]
    if title_pids and _kill_pids(title_pids):
        return True

    # 3) Last resort: focus a window with this name and close it via hotkey.
    for candidate in (app_name, _normalize(app_name)):
        if _focus_app_window(candidate):
            before_pid = _get_foreground_pid_windows()
            if before_pid and _is_browser_pid(before_pid):
                continue  # don't Alt+F4 a browser just because a tab matched
            time.sleep(0.4)
            if _OS == "Darwin":
                pyautogui.hotkey("command", "q")
            else:
                pyautogui.hotkey("alt", "f4")
            time.sleep(0.6)
            after_pid = _get_foreground_pid_windows()
            if before_pid and after_pid != before_pid:
                return True
            if before_pid and not _processes_running(set(), {before_pid}):
                return True

    return False


def close_app(app_name: str | None = None) -> str:
    if app_name:
        label = app_name
        if _close_app_by_name(app_name):
            return f"Closed {label}."
        return f"Could not close {label}. Try saying the exact game name."

    if _close_foreground_app():
        return "Closed active window."
    if _OS == "Darwin":
        pyautogui.hotkey("command", "q")
    else:
        pyautogui.hotkey("alt", "f4")
    return "Sent close command to active window."

def close_window():
    if _OS == "Darwin": pyautogui.hotkey("command", "w")
    else:               pyautogui.hotkey("ctrl", "w")

def full_screen():
    if _OS == "Darwin": pyautogui.hotkey("ctrl", "command", "f")
    else:               pyautogui.press("f11")

def minimize_window():
    if _OS == "Darwin": pyautogui.hotkey("command", "m")
    else:               pyautogui.hotkey("win", "down")

def maximize_window():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to keystroke "f" '
            'using {control down, command down}'],
            capture_output=True)
    elif _OS == "Windows":
        pyautogui.hotkey("win", "up")
    else:
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-b", "add,maximized_vert,maximized_horz"],
                capture_output=True)
        except Exception:
            pyautogui.hotkey("super", "up")

def snap_left():
    if _OS == "Windows":
        pyautogui.hotkey("win", "left")
    elif _OS == "Darwin":
        # macOS has no built-in snap; try Rectangle app shortcut if installed
        try:
            subprocess.run(["open", "-a", "Rectangle"], capture_output=True, timeout=1)
        except Exception:
            pass
        pyautogui.hotkey("ctrl", "option", "left")
    else:  # Linux
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-e", "0,0,0,960,1080"],
                capture_output=True)
        except Exception:
            pass

def snap_right():
    if _OS == "Windows":
        pyautogui.hotkey("win", "right")
    elif _OS == "Darwin":
        try:
            subprocess.run(["open", "-a", "Rectangle"], capture_output=True, timeout=1)
        except Exception:
            pass
        pyautogui.hotkey("ctrl", "option", "right")
    else:  # Linux
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-e", "0,960,0,960,1080"],
                capture_output=True)
        except Exception:
            pass

def switch_window():
    if _OS == "Darwin": pyautogui.hotkey("command", "tab")
    else:               pyautogui.hotkey("alt", "tab")

def show_desktop():
    if _OS == "Darwin":   pyautogui.hotkey("fn", "f11")
    elif _OS == "Windows": pyautogui.hotkey("win", "d")
    else:                  pyautogui.hotkey("super", "d")

def open_task_manager():
    if _OS == "Windows":
        pyautogui.hotkey("ctrl", "shift", "esc")
    elif _OS == "Darwin":
        subprocess.Popen(["open", "-a", "Activity Monitor"])
    else:
        for cmd in [["gnome-system-monitor"], ["xfce4-taskmanager"], ["htop"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                break


def focus_search():
    if _OS == "Darwin": pyautogui.hotkey("command", "l")
    else:               pyautogui.hotkey("ctrl", "l")

def pause_video():      pyautogui.press("space")

def refresh_page():
    if _OS == "Darwin": pyautogui.hotkey("command", "r")
    else:               pyautogui.press("f5")

def close_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "w")
    else:               pyautogui.hotkey("ctrl", "w")

def new_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "t")
    else:               pyautogui.hotkey("ctrl", "t")

def next_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "shift", "bracketright")
    else:               pyautogui.hotkey("ctrl", "tab")

def prev_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "shift", "bracketleft")
    else:               pyautogui.hotkey("ctrl", "shift", "tab")

def go_back():
    if _OS == "Darwin": pyautogui.hotkey("command", "left")
    else:               pyautogui.hotkey("alt", "left")

def go_forward():
    if _OS == "Darwin": pyautogui.hotkey("command", "right")
    else:               pyautogui.hotkey("alt", "right")

def zoom_in():
    if _OS == "Darwin": pyautogui.hotkey("command", "equal")
    else:               pyautogui.hotkey("ctrl", "equal")

def zoom_out():
    if _OS == "Darwin": pyautogui.hotkey("command", "minus")
    else:               pyautogui.hotkey("ctrl", "minus")

def zoom_reset():
    if _OS == "Darwin": pyautogui.hotkey("command", "0")
    else:               pyautogui.hotkey("ctrl", "0")

def find_on_page():
    if _OS == "Darwin": pyautogui.hotkey("command", "f")
    else:               pyautogui.hotkey("ctrl", "f")

def reload_page_n(n: int):
    for _ in range(max(1, n)):
        refresh_page()
        time.sleep(0.8)


def scroll_up(amount: int = 500):    pyautogui.scroll(amount)
def scroll_down(amount: int = 500):  pyautogui.scroll(-amount)

def scroll_top():
    if _OS == "Darwin": pyautogui.hotkey("command", "up")
    else:               pyautogui.hotkey("ctrl", "home")

def scroll_bottom():
    if _OS == "Darwin": pyautogui.hotkey("command", "down")
    else:               pyautogui.hotkey("ctrl", "end")

def page_up():   pyautogui.press("pageup")
def page_down(): pyautogui.press("pagedown")


def copy():
    if _OS == "Darwin": pyautogui.hotkey("command", "c")
    else:               pyautogui.hotkey("ctrl", "c")

def paste():
    if _OS == "Darwin": pyautogui.hotkey("command", "v")
    else:               pyautogui.hotkey("ctrl", "v")

def cut():
    if _OS == "Darwin": pyautogui.hotkey("command", "x")
    else:               pyautogui.hotkey("ctrl", "x")

def undo():
    if _OS == "Darwin": pyautogui.hotkey("command", "z")
    else:               pyautogui.hotkey("ctrl", "z")

def redo():
    if _OS == "Darwin": pyautogui.hotkey("command", "shift", "z")
    else:               pyautogui.hotkey("ctrl", "y")

def select_all():
    if _OS == "Darwin": pyautogui.hotkey("command", "a")
    else:               pyautogui.hotkey("ctrl", "a")

def save_file():
    if _OS == "Darwin": pyautogui.hotkey("command", "s")
    else:               pyautogui.hotkey("ctrl", "s")

def press_enter():   pyautogui.press("enter")
def press_escape():  pyautogui.press("escape")
def press_key(key: str): pyautogui.press(key)

def type_text(text: str, press_enter_after: bool = False):
    if not text:
        return
    if _PYPERCLIP:
        pyperclip.copy(str(text))
        time.sleep(0.15)
        paste()
    else:
        pyautogui.write(str(text), interval=0.03)
    if press_enter_after:
        time.sleep(0.1)
        pyautogui.press("enter")

def take_screenshot():
    if _OS == "Windows":
        pyautogui.hotkey("win", "shift", "s")
    elif _OS == "Darwin":
        pyautogui.hotkey("command", "shift", "3")
    else:
        for cmd in [["scrot"], ["gnome-screenshot"], ["import", "-window", "root", "screenshot.png"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                return
        pyautogui.hotkey("ctrl", "print_screen")

def lock_screen():
    if _OS == "Windows":
        pyautogui.hotkey("win", "l")
    elif _OS == "Darwin":
        subprocess.run(["pmset", "displaysleepnow"], capture_output=True)
    else:
        for cmd in [
            ["gnome-screensaver-command", "-l"],
            ["xdg-screensaver", "lock"],
            ["loginctl", "lock-session"],
        ]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.run(cmd, capture_output=True)
                return

def open_system_settings():
    if _OS == "Windows":
        pyautogui.hotkey("win", "i")
    elif _OS == "Darwin":
        subprocess.Popen(["open", "-a", "System Preferences"])
    else:
        for cmd in [["gnome-control-center"], ["xfce4-settings-manager"], ["kcmshell5"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                return

def open_file_explorer():
    if _OS == "Windows":
        pyautogui.hotkey("win", "e")
    elif _OS == "Darwin":
        subprocess.Popen(["open", str(Path.home())])
    else:
        for cmd in [["nautilus"], ["thunar"], ["dolphin"], ["nemo"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                return
        subprocess.Popen(["xdg-open", str(Path.home())])

def sleep_display():
    if _OS == "Windows":
        try:
            import ctypes
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
        except Exception as e:
            print(f"[Settings] sleep_display failed: {e}")
    elif _OS == "Darwin":
        subprocess.run(["pmset", "displaysleepnow"], capture_output=True)
    else:
        subprocess.run(["xset", "dpms", "force", "off"], capture_output=True)

def open_run():
    if _OS == "Windows":
        pyautogui.hotkey("win", "r")

def dark_mode():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell app "System Events" to tell appearance preferences '
            'to set dark mode to not dark mode'],
            capture_output=True)
    elif _OS == "Windows":
        try:
            import winreg
            key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            current, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, 1 - current)
            winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, 1 - current)
            winreg.CloseKey(key)
        except Exception as e:
            print(f"[Settings] dark_mode registry failed: {e}")
    else:
        try:
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True
            )
            current = result.stdout.strip()
            new_scheme = "'default'" if "dark" in current else "'prefer-dark'"
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", new_scheme],
                capture_output=True
            )
        except Exception as e:
            print(f"[Settings] dark_mode Linux failed: {e}")

def toggle_wifi():
    if _OS == "Darwin":
        iface = _get_macos_wifi_interface()
        result = subprocess.run(
            ["networksetup", "-getairportpower", iface],
            capture_output=True, text=True
        )
        state = "off" if "On" in result.stdout else "on"
        subprocess.run(["networksetup", "-setairportpower", iface, state],
            capture_output=True)
    elif _OS == "Windows":
        try:
            subprocess.run(
                ["powershell", "-Command",
                 "$adapter = Get-NetAdapter | Where-Object {$_.PhysicalMediaType -eq 'Native 802.11'};"
                 "if ($adapter.Status -eq 'Up') { Disable-NetAdapter -Name $adapter.Name -Confirm:$false }"
                 "else { Enable-NetAdapter -Name $adapter.Name -Confirm:$false }"],
                capture_output=True, timeout=10, **_WIN_HIDE
            )
        except Exception as e:
            print(f"[Settings] toggle_wifi Windows failed: {e}")
    else:
        try:
            result = subprocess.run(["nmcli", "radio", "wifi"], capture_output=True, text=True)
            state  = "off" if "enabled" in result.stdout else "on"
            subprocess.run(["nmcli", "radio", "wifi", state], capture_output=True)
        except Exception as e:
            print(f"[Settings] toggle_wifi Linux failed: {e}")

def restart_computer():
    if _OS == "Windows":
        subprocess.run(["shutdown", "/r", "/t", "10"], capture_output=True, **_WIN_HIDE)
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to restart'],
            capture_output=True)
    else:
        subprocess.run(["systemctl", "reboot"], capture_output=True)

def shutdown_computer():
    if _OS == "Windows":
        subprocess.run(["shutdown", "/s", "/t", "10"], capture_output=True)
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to shut down'],
            capture_output=True)
    else:
        subprocess.run(["systemctl", "poweroff"], capture_output=True)

ACTION_MAP: dict[str, callable] = {
    "volume_up":           volume_up,
    "volume_down":         volume_down,
    "mute":                volume_mute,
    "unmute":              volume_mute,
    "toggle_mute":         volume_mute,
    "brightness_up":       brightness_up,
    "brightness_down":     brightness_down,
    "sleep_display":       sleep_display,
    "screen_off":          sleep_display,
    "pause_video":         pause_video,
    "play_pause":          pause_video,
    "close_app":           close_app,
    "close_window":        close_window,
    "full_screen":         full_screen,
    "fullscreen":          full_screen,
    "minimize":            minimize_window,
    "maximize":            maximize_window,
    "snap_left":           snap_left,
    "snap_right":          snap_right,
    "switch_window":       switch_window,
    "show_desktop":        show_desktop,
    "task_manager":        open_task_manager,
    "focus_search":        focus_search,
    "refresh_page":        refresh_page,
    "reload":              refresh_page,
    "close_tab":           close_tab,
    "new_tab":             new_tab,
    "next_tab":            next_tab,
    "prev_tab":            prev_tab,
    "go_back":             go_back,
    "go_forward":          go_forward,
    "zoom_in":             zoom_in,
    "zoom_out":            zoom_out,
    "zoom_reset":          zoom_reset,
    "find_on_page":        find_on_page,
    "scroll_up":           scroll_up,
    "scroll_down":         scroll_down,
    "scroll_top":          scroll_top,
    "scroll_bottom":       scroll_bottom,
    "page_up":             page_up,
    "page_down":           page_down,
    "copy":                copy,
    "paste":               paste,
    "cut":                 cut,
    "undo":                undo,
    "redo":                redo,
    "select_all":          select_all,
    "save":                save_file,
    "enter":               press_enter,
    "escape":              press_escape,
    "screenshot":          take_screenshot,
    "lock_screen":         lock_screen,
    "open_settings":       open_system_settings,
    "file_explorer":       open_file_explorer,
    "open_run":            open_run,
    "dark_mode":           dark_mode,
    "toggle_wifi":         toggle_wifi,
    "restart":             restart_computer,
    "shutdown":            shutdown_computer,
}

_DANGEROUS_ACTIONS = {"restart", "shutdown"}



def _detect_action(description: str) -> dict:

    from google import genai as _genai
    _client = _genai.Client(api_key=_get_api_key())

    available = ", ".join(sorted(ACTION_MAP.keys())) + \
                ", volume_set, type_text, press_key, reload_n"

    prompt = f"""You are an intent detector for a computer control assistant.

The user issued a command (possibly in any language): "{description}"

Available actions: {available}

Return ONLY a valid JSON object:
{{"action": "action_name", "value": null_or_value}}

Rules:
- Pick the single best matching action from the available list.
- For close_app: value is the application or game name to close (e.g. "Discord", "Counter-Strike 2", "cs2"). Use null when closing the currently active game or window.
- For volume_set: value is an integer 0-100.
- For type_text: value is the exact text to type.
- For press_key: value is the key name (e.g. "f5", "tab", "enter").
- For reload_n: value is an integer (number of times to reload).
- If no clear match, pick the closest action.
- Return ONLY the JSON, no explanation, no markdown."""

    try:
        resp = _client.models.generate_content(model="gemini-3.5-flash-lite", contents=prompt)
        text = re.sub(r"```(?:json)?", "", resp.text).strip().rstrip("`").strip()
        return json.loads(text)
    except Exception as e:
        print(f"[Settings] Intent detection failed: {e}")
        return {"action": description.lower().replace(" ", "_"), "value": None}

def computer_settings(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    if not _PYAUTOGUI:
        return "pyautogui is not installed. Run: pip install pyautogui"

    params      = parameters or {}
    raw_action  = params.get("action", "").strip()
    description = params.get("description", "").strip()
    value       = params.get("value", None)

    if not raw_action and description:
        detected   = _detect_action(description)
        raw_action = detected.get("action", "")
        if value is None:
            value = detected.get("value")

    action = raw_action.lower().strip().replace(" ", "_").replace("-", "_")

    if not action:
        return "No action could be determined."

    print(f"[Settings] Action: {action}  Value: {value}  OS: {_OS}")
    if player:
        player.write_log(f"[Settings] {action}")

    if action in _DANGEROUS_ACTIONS:
        confirmed = str(params.get("confirmed", "")).lower()
        if confirmed not in ("yes", "true", "1", "confirm"):
            return (
                f"This will {action} the computer. "
                f"Please confirm by calling again with confirmed=yes."
            )

    if action in ("volume_set", "volume", "set_volume"):
        if value is None:
            return ("Please provide a volume level (value 0-100), "
                    "or use volume_up / volume_down / mute.")
        try:
            volume_set(int(value))
            return f"Volume set to {value}%."
        except Exception as e:
            return f"Could not set volume: {e}"

    if action in ("type_text", "write_on_screen", "type", "write"):
        text = str(value or params.get("text", "")).strip()
        if not text:
            return "No text provided to type."
        enter_after = str(params.get("press_enter", "false")).lower() in ("true", "1", "yes")
        type_text(text, press_enter_after=enter_after)
        return f"Typed: {text[:80]}"

    if action == "press_key":
        key = str(value or params.get("key", "")).strip()
        if not key:
            return "No key specified."
        press_key(key)
        return f"Pressed: {key}"

    if action in ("reload_n", "refresh_n", "reload_page_n"):
        try:
            reload_page_n(int(value or 1))
            return f"Reloaded {value or 1} time(s)."
        except Exception as e:
            return f"Reload failed: {e}"

    if action == "close_app":
        app_name = str(
            value or params.get("app_name") or params.get("text") or ""
        ).strip()
        if not app_name and description:
            app_name = _extract_app_name_from_description(description)
        try:
            result = close_app(app_name or None)
            return result
        except Exception as e:
            print(f"[Settings] close_app failed: {e}")
            return f"Could not close app: {e}"

    if action == "scroll_up":
        scroll_up(int(value or 500))
        return "Scrolled up."

    if action == "scroll_down":
        scroll_down(int(value or 500))
        return "Scrolled down."

    func = ACTION_MAP.get(action)
    if not func:
        return f"Unknown action: '{raw_action}'."

    try:
        func()
        return f"Done: {action}."
    except Exception as e:
        print(f"[Settings] Action failed ({action}): {e}")
        return f"Action failed ({action}): {e}"