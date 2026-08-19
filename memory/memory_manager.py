from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

# Avoid UnicodeEncodeError on Windows consoles (cp1251/cp866): emoji and other
# non-ASCII in print() must never crash the app — replace undecodable chars.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR     = get_base_dir()
MEMORY_PATH  = BASE_DIR / "memory" / "long_term.json"     # legacy flat store (migrated once)
MONITORS_PATH = BASE_DIR / "memory" / "store" / "monitors.json"  # background-monitor state

_lock         = threading.Lock()        # guards monitor-file writes (legacy consumers)
_migrate_lock = threading.Lock()        # guards the one-time flat→layered migration

_CATEGORIES = ("identity", "preferences", "projects", "relationships", "wishes", "notes")


def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
    }


# ── One-time migration: legacy flat long_term.json → layered store ────────────

def migrate_legacy_flat() -> int:
    """
    One-time import of the legacy flat ``long_term.json`` into the layered store.

    * Facts (identity/preferences/projects/relationships/wishes/notes) are copied
      into the ``long_term`` layer, but only when that ``(category, key)`` is not
      already present — the layered store is authoritative, so we never overwrite
      a newer value with an older flat one.
    * Sessions are copied into the ``episodic`` layer only if no session entry
      already exists there (the episodic store already supersedes the flat list).
    * Monitors are moved to their dedicated state file ``memory/store/monitors.json``.

    On success the flat file is renamed to ``long_term.json.bak`` so it is never
    read again. Returns the number of entries migrated.
    """
    with _migrate_lock:
        if not MEMORY_PATH.exists():
            return 0

        migrated = 0
        migration_complete = True
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}

            from memory.layered_memory import add_memory, get_layer, record_session

            existing = get_layer("long_term")
            existing_keys = set()
            for e in existing:
                labels = e.get("labels") or []
                if len(labels) >= 2:
                    existing_keys.add((labels[0], labels[1]))

            for cat in _CATEGORIES:
                items = data.get(cat)
                if not isinstance(items, dict):
                    continue
                for key, entry in items.items():
                    if (cat, str(key)) in existing_keys:
                        continue          # already in layered — keep the newer value
                    val = entry.get("value") if isinstance(entry, dict) else entry
                    if val is None or not str(val).strip():
                        continue
                    try:
                        add_memory(
                            content=f"{str(key).replace('_', ' ')}: {val}",
                            layer="long_term", labels=[cat, str(key)],
                            source="migration", embed_async=False,
                        )
                        migrated += 1
                    except Exception as e:
                        print(f"[Memory] ⚠️ migrate {cat}/{key}: {e}")
                        migration_complete = False

            # Sessions → episodic (only if episodic has no session entries yet).
            sessions = data.get("sessions")
            if isinstance(sessions, list):
                has_session = any(
                    e.get("kind") == "session" for e in get_layer("episodic")
                )
                if not has_session:
                    for s in sessions:
                        if isinstance(s, dict) and s.get("summary"):
                            try:
                                record_session(str(s["summary"]), str(s.get("language", "")))
                                migrated += 1
                            except Exception as e:
                                print(f"[Memory] ⚠️ migrate session: {e}")
                                migration_complete = False

            # Monitors → dedicated state file.
            monitors = data.get("monitors")
            if isinstance(monitors, dict) and monitors:
                _migrate_monitors(monitors)
        except Exception as e:
            print(f"[Memory] ⚠️ migration error: {e}")
            return migrated

        if not migration_complete:
            print("[Memory] ⚠️ migration incomplete; preserving legacy file for retry")
            return migrated

        try:
            MEMORY_PATH.replace(MEMORY_PATH.with_name("long_term.json.bak"))
            print(f"[Memory] ✅ Migrated {migrated} legacy entries → layered store (long_term.json → .bak)")
        except Exception as e:
            print(f"[Memory] ⚠️ could not rename legacy file: {e}")
        return migrated


def _migrate_monitors(monitors: dict) -> None:
    if MONITORS_PATH.exists():
        return
    MONITORS_PATH.parent.mkdir(parents=True, exist_ok=True)
    MONITORS_PATH.write_text(
        json.dumps(monitors, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ── Monitor state (dedicated file, not memory) ────────────────────────────────

def load_monitors() -> dict:
    if not MONITORS_PATH.exists():
        return {}
    try:
        data = json.loads(MONITORS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[Memory] ⚠️ load monitors error: {e}")
        return {}


def save_monitors(monitors: dict) -> None:
    MONITORS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        MONITORS_PATH.write_text(
            json.dumps(monitors, indent=2, ensure_ascii=False), encoding="utf-8"
        )


# ── Layered-backed flat view ───────────────────────────────────────────────────

def _flat_view_from_layered() -> dict:
    """Reconstruct the legacy flat structure from the layered long_term layer.

    Only ``category/key: value`` facts (labels = [category, key]) are mapped back;
    free-text facts remain available via the layered ``format_layered_memory_context``.
    """
    view = _empty_memory()
    try:
        from memory.layered_memory import get_layer
        for e in get_layer("long_term"):
            labels = e.get("labels") or []
            if len(labels) < 2 or labels[0] not in _CATEGORIES or not labels[1]:
                continue
            cat, key = labels[0], labels[1]
            content = e.get("content") or ""
            prefix = f"{str(key).replace('_', ' ')}: "
            value = content[len(prefix):] if content.lower().startswith(prefix.lower()) else content
            view[cat][str(key)] = {
                "value": str(value),
                "updated": (e.get("updated") or "")[:10],
            }
    except Exception as e:
        print(f"[Memory] ⚠️ flat view failed: {e}")
    return view


def load_memory() -> dict:
    """
    Return the memory dict backed by the layered store (single source of truth).

    Triggers a one-time migration of the legacy flat ``long_term.json`` on first
    use, then reconstructs the flat view from the layered ``long_term`` layer for
    backward-compatible callers.
    """
    migrate_legacy_flat()
    view = _flat_view_from_layered()
    view["sessions"]  = []
    view["monitors"]  = load_monitors()
    return view


def save_memory(memory: dict) -> None:
    """Persist a full flat memory dict to the layered store."""
    update_memory(memory)


def update_memory(memory_update: dict) -> dict:
    """Write flat ``{category: {key: {"value": ...}}}`` facts into the layered store."""
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()

    from memory.layered_memory import add_memory
    changed = False
    for category, items in memory_update.items():
        if not isinstance(items, dict):
            continue
        for key, val in items.items():
            value = val.get("value") if isinstance(val, dict) else val
            if value is None or not str(value).strip():
                continue
            try:
                add_memory(
                    content=f"{str(key).replace('_', ' ')}: {value}",
                    layer="long_term", labels=[str(category), str(key)],
                    source="auto", embed_async=True,
                )
                changed = True
            except Exception as e:
                print(f"[Memory] ⚠️ update_memory {category}/{key}: {e}")

    if changed:
        print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")
    return load_memory()


def format_memory_for_prompt(memory: dict | None) -> str:
    if not memory:
        return ""

    lines = []

    identity  = memory.get("identity", {})
    id_fields = ["name", "age", "birthday", "city", "job", "language", "school", "nationality"]
    for field in id_fields:
        entry = identity.get(field)
        if entry:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if key in id_fields:
            continue
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{key.replace('_', ' ').title()}: {val}")

    prefs = memory.get("preferences", {})
    if prefs:
        lines.append("")
        lines.append("Preferences:")
        for key, entry in list(prefs.items())[:15]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    projects = memory.get("projects", {})
    if projects:
        lines.append("")
        lines.append("Active Projects / Goals:")
        for key, entry in list(projects.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    rels = memory.get("relationships", {})
    if rels:
        lines.append("")
        lines.append("People in their life:")
        for key, entry in list(rels.items())[:10]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    wishes = memory.get("wishes", {})
    if wishes:
        lines.append("")
        lines.append("Wishes / Plans / Wants:")
        for key, entry in list(wishes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    notes = memory.get("notes", {})
    if notes:
        lines.append("")
        lines.append("Other notes:")
        for key, entry in list(notes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key}: {val}")

    if not lines:
        return ""

    header = "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]\n"
    result = header + "\n".join(lines)
    if len(result) > 2000:
        result = result[:1997] + "…"

    return result + "\n"


def remember(key: str, value: str, category: str = "notes") -> str:
    valid = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}
    if category not in valid:
        category = "notes"
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    from memory.layered_memory import get_layer, forget as _forget
    entries = get_layer("long_term")
    target = None
    for e in entries:
        labels = e.get("labels") or []
        if len(labels) >= 2 and labels[0] == category and labels[1] == str(key):
            target = e
            break
    if target is not None:
        _forget(target["id"], "long_term")
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


forget_memory = forget


# ── Session memory ─────────────────────────────────────────────────────────────

def save_session_summary(summary: str, language: str = "") -> None:
    """Persist a session summary to the episodic layer (single source of truth)."""
    from memory.layered_memory import record_session
    summary = (summary or "").strip()
    if summary:
        record_session(summary, language)


def pop_last_session() -> dict | None:
    """Return AND remove the most recent episodic session entry (consume-once)."""
    from memory.layered_memory import get_layer, forget as _forget
    entries = [e for e in get_layer("episodic") if e.get("kind") == "session"]
    if not entries:
        return None
    entries.sort(key=lambda e: e.get("created", "") or "")
    last = entries[-1]
    _forget(last["id"], "episodic")
    return {
        "date":    last.get("date", ""),
        "summary": last.get("content", ""),
        "language": "",
    }


# ── Multi-layer structured memory bridge ───────────────────────────────────────
# The layered engine (memory/layered_memory.py) is the single source of truth for
# short-term / long-term / project / episodic memory. These thin wrappers expose
# it without the legacy callers needing to know the internals.

def search_memory(query: str, layers=None, top_k: int = 5) -> list[dict]:
    """Semantic/context search across the layered store."""
    from memory.layered_memory import search
    return search(query, layers=layers, top_k=top_k)


def recall_memory(query: str, layers=None, top_k: int = 5) -> str:
    """Formatted memory lookup for the assistant (natural-language text)."""
    from memory.layered_memory import recall
    return recall(query, layers=layers, top_k=top_k)


def add_layer_memory(content: str, layer: str = "long_term", labels=None,
                     importance: float = 0.5, source: str = "auto",
                     kind: str = None, date: str = None) -> dict:
    """Write a structured memory entry into one of the four layers."""
    from memory.layered_memory import add_memory
    return add_memory(
        content=content, layer=layer, labels=labels, importance=importance,
        source=source, kind=kind, date=date,
    )


def guess_memory_layer(content: str) -> str:
    """Best-effort layer classification for free-form memory content."""
    from memory.layered_memory import guess_layer
    return guess_layer(content)


def record_session_event(summary: str, language: str = "") -> dict:
    """Persist a session summary into the episodic layer."""
    from memory.layered_memory import record_session
    return record_session(summary, language)


def record_project_fact(content: str, labels: list[str] | None = None,
                        kind: str = "decision") -> dict:
    """Persist a technical / project fact into the project layer."""
    from memory.layered_memory import add_memory
    return add_memory(
        content=content, layer="project", labels=labels, kind=kind,
        importance=0.7, source="auto",
    )


def format_layered_memory_context(max_chars: int = 1800) -> str:
    """Compact snapshot of the layered store for system-prompt injection."""
    from memory.layered_memory import format_context
    return format_context(max_chars=max_chars)
