# -*- coding: utf-8 -*-
"""
Autonomous file downloader.

Downloads a file from a URL straight to the user's Downloads folder (or a
chosen folder), following redirects and sending a real browser User-Agent so
most download servers accept the request. Optionally installs the result:
runs installers and extracts archives.

This lets JARVIS actually *complete* a "download X" request instead of only
opening a browser and telling the user to do it themselves.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# File extensions that clearly indicate a downloadable file (vs. a web page).
_FILE_EXTS = {
    ".exe", ".msi", ".msix", ".dmg", ".pkg", ".deb", ".rpm", ".appx",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".iso",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico",
    ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus",
    ".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v",
    ".txt", ".md", ".csv", ".json", ".xml", ".py", ".js", ".apk",
}

_ARCHIVE_EXTS = {".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz"}
_INSTALLER_EXTS = {".exe", ".msi", ".msix", ".bat", ".cmd"}


def _downloads_dir() -> Path:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class _GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD),
                            ("Data4", ctypes.c_ubyte * 8)]

            fid = _GUID(0x374DE290, 0x123F, 0x4565,
                        (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4,
                                             0x92, 0x5E, 0x46, 0x7B))
            buf = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(
                    ctypes.byref(fid), 0, None, ctypes.byref(buf)) == 0:
                p = Path(buf.value)
                ctypes.windll.ole32.CoTaskMemFree(buf)
                if p.is_dir():
                    return p
        except Exception:
            pass
    return Path.home() / "Downloads"


def _filename_from_cd(cd: str) -> str:
    if not cd:
        return ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd, re.IGNORECASE)
    if m:
        return unquote(m.group(1).strip())
    m = re.search(r'filename="?([^";]+)"?', cd, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def _sanitize(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "download"


def _looks_like_file(url: str) -> bool:
    try:
        path = urlparse(url).path.lower()
    except Exception:
        return False
    for ext in _FILE_EXTS:
        if path.endswith(ext):
            return True
    return False


def _log(player, text: str) -> None:
    print(f"[Downloader] {text}")
    if player is not None:
        try:
            player.write_log(f"[download] {text}")
        except Exception:
            pass


def _install(path: Path) -> str:
    ext = path.suffix.lower()
    try:
        if ext in _ARCHIVE_EXTS:
            out = path.with_suffix("")
            out.mkdir(parents=True, exist_ok=True)
            shutil.unpack_archive(str(path), str(out))
            return f"Extracted to {out}."
        if ext == ".7z":
            try:
                subprocess.run(["7z", "x", str(path),
                                f"-o{path.with_suffix('')}", "-y"],
                               check=True, capture_output=True, timeout=300)
                return f"Extracted to {path.with_suffix('')}."
            except FileNotFoundError:
                return "7-Zip not installed — downloaded, but not extracted."
        if ext == ".rar":
            try:
                subprocess.run(["unrar", "x", "-y", str(path)],
                               check=True, capture_output=True, timeout=300)
                return f"Extracted to {path.with_suffix('')}."
            except FileNotFoundError:
                return "unrar not installed — downloaded, but not extracted."
        if ext in _INSTALLER_EXTS and os.name == "nt":
            if ext == ".msi":
                subprocess.Popen(["msiexec", "/i", str(path)],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen([str(path)], cwd=str(path.parent),
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            return "Installer launched."
        if ext in (".dmg", ".pkg", ".deb", ".rpm"):
            return f"Installer downloaded ({path.name}) — open it on your OS."
        return f"File saved ({path.name}) — no auto-install for '{ext}'."
    except Exception as e:
        return f"File saved, but auto-install failed: {e}"


def download_file(parameters=None, player=None, speak=None) -> str:
    params = parameters or {}
    url = (params.get("url") or "").strip()
    if not url:
        return "No URL provided."
    if "://" not in url:
        url = "https://" + url

    file_name = (params.get("file_name") or "").strip()
    folder = (params.get("folder") or "").strip()
    install = bool(params.get("install", False))

    dest_dir = Path(folder) if folder else _downloads_dir()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return f"Could not create folder '{dest_dir}': {e}"

    _log(player, f"Downloading {url}")

    try:
        headers = {"User-Agent": _USER_AGENT, "Accept": "*/*"}
        with requests.get(url, headers=headers, stream=True,
                          timeout=120, allow_redirects=True) as r:
            r.raise_for_status()

            ctype = (r.headers.get("Content-Type") or "").lower()
            if "text/html" in ctype and not _looks_like_file(url):
                # It's a download PAGE, not a direct file. Delegate to the
                # browser, which clicks the download button itself.
                _log(player, f"{url} is a page — clicking its download button in the browser.")
                try:
                    from actions.browser_control import browser_control
                    return browser_control(
                        {"action": "download", "url": url, "folder": folder},
                        player=player,
                    )
                except Exception as e:
                    return f"Download failed (page, not a direct file): {e}"

            cd = r.headers.get("Content-Disposition", "")
            name = file_name or _filename_from_cd(cd) or Path(urlparse(url).path).name
            name = _sanitize(name)
            if not name:
                name = "download"
            dest = dest_dir / name

            size = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
                    size += len(chunk)

        mb = size / (1024 * 1024)
        result = f"Downloaded '{dest.name}' to {dest.parent} ({mb:.1f} MB)."
        if install:
            result += " " + _install(dest)
        _log(player, result)
        return result
    except requests.HTTPError as e:
        code = getattr(getattr(e, "response", None), "status_code", "?")
        return f"Download failed (HTTP {code}): {url}"
    except Exception as e:
        return f"Download failed: {e}"
