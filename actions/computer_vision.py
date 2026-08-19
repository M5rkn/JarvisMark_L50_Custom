"""On-demand desktop vision helpers.

Captures are intentionally transient: this module only returns image bytes to the
caller and never writes screenshots to disk.  Every capture is requested by a
tool call or post-action verification; it does not start a polling loop.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import io
import sys
from dataclasses import dataclass

try:
    import mss
    import mss.tools
    _MSS = True
except ImportError:
    _MSS = False

try:
    from PIL import Image, ImageGrab
    _PIL = True
except ImportError:
    _PIL = False

try:
    import pytesseract
    _OCR = True
except ImportError:
    _OCR = False


@dataclass(frozen=True)
class CaptureInfo:
    target: str
    bounds: tuple[int, int, int, int]
    active_window: str = ""


def _active_window() -> tuple[str, tuple[int, int, int, int] | None]:
    """Return the foreground Windows window title and bounds when available."""
    if sys.platform != "win32":
        return "", None
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "", None
        length = user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, len(title_buf))
        rect = ctypes.wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return title_buf.value, None
        return title_buf.value, (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    except Exception:
        return "", None


def list_windows(limit: int = 20) -> list[dict]:
    """List visible top-level Windows windows; returns an empty list elsewhere."""
    if sys.platform != "win32":
        return []
    found: list[dict] = []
    try:
        user32 = ctypes.windll.user32
        foreground = user32.GetForegroundWindow()
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if not length:
                return True
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, len(title))
            rect = ctypes.wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                found.append({
                    "title": title.value,
                    "bounds": [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top],
                    "active": hwnd == foreground,
                })
            return len(found) < limit

        user32.EnumWindows(callback_type(callback), 0)
    except Exception:
        return []
    return found


def _normalise_region(region: dict | None, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if not region:
        return fallback
    try:
        x, y = int(region["x"]), int(region["y"])
        width, height = int(region["width"]), int(region["height"])
        if width > 0 and height > 0:
            return x, y, width, height
    except (KeyError, TypeError, ValueError):
        pass
    raise ValueError("Region needs integer x, y, width and height greater than zero.")


def capture_screen(target: str = "fullscreen", region: dict | None = None) -> tuple[bytes, str, CaptureInfo]:
    """Capture a full screen, active window, or explicit region into memory."""
    if not (_MSS or _PIL):
        raise RuntimeError("Desktop capture needs mss or Pillow. Run: pip install mss pillow")
    target = (target or "fullscreen").lower()
    if target not in {"fullscreen", "active_window", "region"}:
        raise ValueError("target must be fullscreen, active_window, or region")

    title, active_bounds = _active_window()
    if _MSS:
        with mss.mss() as sct:
            full = sct.monitors[0]  # virtual desktop: every monitor
            fallback = (full["left"], full["top"], full["width"], full["height"])
            if target == "active_window":
                bounds = active_bounds or fallback
            elif target == "region":
                bounds = _normalise_region(region, fallback)
            else:
                bounds = fallback
            x, y, width, height = bounds
            shot = sct.grab({"left": x, "top": y, "width": width, "height": height})
            png = mss.tools.to_png(shot.rgb, shot.size)
    else:
        try:
            full_image = ImageGrab.grab(all_screens=True)
        except Exception as e:
            raise RuntimeError(f"Pillow screen capture failed: {e}") from e
        fallback = (0, 0, full_image.width, full_image.height)
        if target == "active_window":
            bounds = active_bounds or fallback
        elif target == "region":
            bounds = _normalise_region(region, fallback)
        else:
            bounds = fallback
        x, y, width, height = bounds
        try:
            image = full_image if bounds == fallback else ImageGrab.grab(bbox=(x, y, x + width, y + height))
        except Exception as e:
            raise RuntimeError(f"Pillow region capture failed: {e}") from e
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        png = buffer.getvalue()
    return png, "image/png", CaptureInfo(target=target, bounds=bounds, active_window=title)


def inspect_visible_text(image_bytes: bytes, max_items: int = 40) -> list[dict]:
    """Run local OCR and return text boxes. Missing OCR support is non-fatal."""
    if not (_OCR and _PIL):
        return []
    try:
        data = pytesseract.image_to_data(Image.open(io.BytesIO(image_bytes)), output_type=pytesseract.Output.DICT)
        items = []
        for i, raw in enumerate(data.get("text", [])):
            text = (raw or "").strip()
            try:
                confidence = float(data["conf"][i]) / 100
            except (IndexError, TypeError, ValueError):
                confidence = 0.0
            if text and confidence >= 0.35:
                items.append({
                    "text": text,
                    "confidence": round(confidence, 2),
                    "bounds": [int(data["left"][i]), int(data["top"][i]), int(data["width"][i]), int(data["height"][i])],
                })
        return items[:max_items]
    except Exception:
        return []


def describe_capture(image_bytes: bytes, info: CaptureInfo) -> str:
    """Compact trusted metadata accompanying an on-demand vision request."""
    words = inspect_visible_text(image_bytes)
    parts = [f"Capture target={info.target}; bounds={info.bounds}."]
    if info.active_window:
        parts.append(f"Active window title={info.active_window!r}.")
    if words:
        text = " ".join(item["text"] for item in words[:20])
        parts.append(f"Local OCR (may be incomplete): {text[:700]}")
    else:
        parts.append("Local OCR unavailable or found no confident text; inspect the image directly.")
    return " ".join(parts)
