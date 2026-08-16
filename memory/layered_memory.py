# -*- coding: utf-8 -*-
"""
Multi-layer structured memory engine for JARVIS.

Four layers, each persisted to its own JSON file under ``memory/store/``:

    short_term  — current conversation, active task, recent context (auto-pruned)
    long_term   — user preferences, habits, important facts, recurring patterns
    project     — project structure, technologies, configurations, past errors,
                  fixes, decisions
    episodic    — past sessions, completed tasks, changes made, important events

Design goals
------------
* **Semantic retrieval** — search by meaning, not just exact keywords. Uses the
  Gemini ``text-embedding-004`` model when an API key is available, and falls
  back to a dependency-free character/word n-gram vector for lexical similarity.
* **Automatic dedup** — adding a fact that already exists updates the existing
  entry (refreshing its content + timestamp) instead of creating a duplicate.
* **Outdated-info correction** — newer content for the same fact overwrites the
  stale value while preserving its original ``created`` timestamp.
* **Persistence** — every layer survives restarts; all writes are locked.

This module is import-safe: it must not import PyQt, sounddevice, numpy, or the
Gemini client at module import time (only stdlib here). The Gemini client is
imported lazily inside :func:`embed`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE_DIR   = _base_dir()
_STORE_DIR  = _BASE_DIR / "memory" / "store"
_EMBED_MODEL = "text-embedding-004"

# ── Layers ─────────────────────────────────────────────────────────────────────

SHORT_TERM = "short_term"
LONG_TERM  = "long_term"
PROJECT    = "project"
EPISODIC   = "episodic"

LAYERS = (SHORT_TERM, LONG_TERM, PROJECT, EPISODIC)

# ── Tunables ───────────────────────────────────────────────────────────────────

_LEX_DUP_THRESHOLD  = 0.70   # lexical similarity above which an add = update
_SEM_DUP_THRESHOLD  = 0.90   # semantic similarity used by consolidate()/merge
_DEFAULT_IMPORTANCE = 0.5
_SHORT_TERM_MAX     = 30     # prune oldest beyond this many short-term entries
_SHORT_TERM_TTL_DAYS = 7     # drop short-term entries older than this
_FEATURE_DIMS       = 512    # dimensionality of the local fallback vector

_lock = threading.RLock()            # guards all store read-modify-write
_client = None                       # lazy Gemini client (cached)
_client_lock = threading.Lock()

# ── Low-level JSON store I/O ───────────────────────────────────────────────────

def _layer_file(layer: str) -> Path:
    if layer not in LAYERS:
        raise ValueError(f"Unknown memory layer: {layer!r} (expected one of {LAYERS})")
    return _STORE_DIR / f"{layer}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load(layer: str) -> list[dict]:
    path = _layer_file(layer)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("entries", []) if isinstance(data, dict) else []
        return [e for e in entries if isinstance(e, dict)]
    except Exception as e:
        print(f"[LayeredMemory] ⚠️ Load error ({layer}): {e}")
        return []


def _save(layer: str, entries: list[dict]) -> None:
    _STORE_DIR.mkdir(parents=True, exist_ok=True)
    doc = {"layer": layer, "version": 1, "updated": _now(), "entries": entries}
    _layer_file(layer).write_text(
        json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ── Vector helpers (embeddings + dependency-free fallback) ─────────────────────

def _get_client():
    """Return a lazily-created Gemini client, or None if no key is configured."""
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        try:
            from memory.config_manager import get_gemini_key
            key = get_gemini_key()
        except Exception:
            key = None
        if not key:
            _client = False  # sentinel: no key, don't retry
            return None
        try:
            from google import genai
            _client = genai.Client(api_key=key)
        except Exception as e:
            print(f"[LayeredMemory] ⚠️ Gemini client unavailable: {e}")
            _client = False
    return _client or None


def embed(text: str) -> list[float] | None:
    """
    Return a semantic embedding for ``text``, or None when unavailable.
    Falls back to the local feature vector is handled by callers, not here.
    """
    text = (text or "").strip()
    if not text:
        return None
    client = _get_client()
    if not client:
        return None
    try:
        resp = client.models.embed_content(
            model=_EMBED_MODEL,
            contents=[text],
        )
        values = resp.embeddings[0].values
        return [float(v) for v in values]
    except Exception as e:
        print(f"[LayeredMemory] ⚠️ Embed failed: {e}")
        return None


def _hash_vector(text: str, dims: int = _FEATURE_DIMS) -> list[float]:
    """
    Dependency-free bag-of-n-grams feature hashing vector (unit-normalised).

    Character 3/4-grams plus whole-word tokens are hashed into a fixed-width
    signed vector. This gives cosine similarity a reasonable lexical signal
    without requiring any ML package, and is used whenever embeddings are absent.
    """
    text = re.sub(r"\s+", " ", (text or "").lower().strip())
    if not text:
        return [0.0] * dims
    vec = [0.0] * dims

    def _bump(token: str, weight: float) -> None:
        h = int(hashlib.md5(token.encode("utf-8", errors="ignore")).hexdigest(), 16)
        idx = h % dims
        sign = 1.0 if (h >> 63) & 1 else -1.0
        vec[idx] += sign * weight

    for n in (3, 4):
        if len(text) >= n:
            for i in range(len(text) - n + 1):
                _bump(text[i:i + n], 1.0)
    for word in text.split():
        _bump(word, 2.0)   # whole words carry more weight than substrings

    norm = math.sqrt(sum(v * v for v in vec))
    if norm:
        vec = [v / norm for v in vec]
    return vec


def _cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _entry_score(entry: dict, query_embedding: list[float] | None,
                 query_text: str) -> float:
    """Best available similarity between a query and a stored entry."""
    emb = entry.get("embedding")
    if emb and query_embedding and len(emb) == len(query_embedding):
        sem = _cosine(emb, query_embedding)
        if sem > 0.0:
            return sem
    return _cosine(_hash_vector(entry.get("content", "")), _hash_vector(query_text))


# ── Entry construction ─────────────────────────────────────────────────────────

def _new_entry(content: str, labels: list[str] | None = None,
               importance: float = _DEFAULT_IMPORTANCE, source: str = "auto",
               kind: str | None = None, date: str | None = None) -> dict:
    try:
        importance = max(0.0, min(1.0, float(importance)))
    except (TypeError, ValueError):
        importance = _DEFAULT_IMPORTANCE
    entry: dict = {
        "id": uuid.uuid4().hex[:12],
        "content": content.strip(),
        "labels": [str(l) for l in (labels or []) if str(l).strip()],
        "embedding": None,
        "created": _now(),
        "updated": _now(),
        "importance": importance,
        "source": source or "auto",
    }
    if kind:
        entry["kind"] = kind
    if date:
        entry["date"] = date
    return entry


def _merge_into(existing: dict, content: str, labels: list[str] | None,
                importance: float) -> None:
    """Refresh an existing entry with newer content (outdated-info correction)."""
    existing["content"] = content.strip()
    existing["updated"] = _now()
    existing["importance"] = max(
        existing.get("importance", _DEFAULT_IMPORTANCE),
        float(importance),
    )
    if labels:
        merged = list(existing.get("labels", []))
        for l in labels:
            if str(l).strip() and str(l) not in merged:
                merged.append(str(l))
        existing["labels"] = merged
    existing["embedding"] = None   # re-embed next pass (content changed)


# Keys that legitimately hold several values at once (e.g. a bilingual user's
# "language" is Russian AND English). These must never be collapsed by the
# singleton-fact upsert below — only exact lexical dedup applies to them.
_MULTI_VALUE_KEYS = {"language", "languages"}


def _same_fact_key(in_content: str, in_labels, entry: dict) -> bool:
    """True when ``entry`` stores a "key: value" fact whose key label matches one
    of ``in_labels`` and the incoming content is an updated value for that key.

    This lets a mutable singleton fact (e.g. "age: 19" → "age: 20") be replaced
    by a newer value instead of piling up conflicting entries that lexical dedup
    would never merge (different values ⇒ different text). Multi-valued keys
    (see ``_MULTI_VALUE_KEYS``) are deliberately excluded.
    """
    inc = {str(l).strip().lower() for l in (in_labels or [])}
    ent = {str(l).strip().lower() for l in entry.get("labels", [])}
    etext = (entry.get("content") or "").lower()
    itext = (in_content or "").lower()
    for lab in inc & ent:
        key = lab.replace("_", " ")
        if key in _MULTI_VALUE_KEYS:
            continue
        if key and f"{key}:" in etext and f"{key}:" in itext:
            return True
    return False


# ── Public write API ───────────────────────────────────────────────────────────

def add_memory(content: str, layer: str = LONG_TERM, labels: list[str] | None = None,
               importance: float = _DEFAULT_IMPORTANCE, source: str = "auto",
               kind: str | None = None, date: str | None = None,
               dedup: bool = True, embed_async: bool = True) -> dict:
    """
    Add (or update) a memory entry in ``layer``.

    Returns a small status dict::

        {"id", "layer", "content", "merged": bool}

    When ``dedup`` is true and a lexically-similar entry already exists, the
    existing entry is updated instead of a duplicate being created.
    ``embed_async`` computes the semantic embedding on a background thread so
    the caller never blocks on the network.
    """
    if not content or not str(content).strip():
        return {"id": None, "layer": layer, "content": "", "merged": False}
    content = str(content).strip()
    if layer not in LAYERS:
        layer = LONG_TERM
    try:
        importance = max(0.0, min(1.0, float(importance)))
    except (TypeError, ValueError):
        importance = _DEFAULT_IMPORTANCE

    with _lock:
        entries = _load(layer)
        existing = None
        if dedup:
            new_vec = _hash_vector(content)
            best = None
            best_score = 0.0
            for e in entries:
                s = _cosine(new_vec, _hash_vector(e.get("content", "")))
                if s > best_score:
                    best_score = s
                    best = e
            if best is not None and best_score >= _LEX_DUP_THRESHOLD:
                existing = best

            # Mutable-fact upsert: re-saving "key: value" under the same key
            # label (e.g. "language: Russian" → "language: English") replaces
            # the old value instead of accumulating conflicting entries.
            if existing is None and labels:
                for e in entries:
                    if _same_fact_key(content, labels, e):
                        existing = e
                        break

        if existing is not None:
            _merge_into(existing, content, labels, importance)
            merged = True
            entry_id = existing["id"]
        else:
            entry = _new_entry(content, labels, importance, source, kind, date)
            entries.append(entry)
            merged = False
            entry_id = entry["id"]

        if layer == SHORT_TERM:
            entries = _prune_short_term(entries)
        _save(layer, entries)

    if embed_async and entry_id:
        _spawn_embed(layer, entry_id)
    return {"id": entry_id, "layer": layer, "content": content, "merged": merged}


def _prune_short_term(entries: list[dict]) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=_SHORT_TERM_TTL_DAYS)).isoformat(
        timespec="seconds"
    )
    kept = []
    for e in entries:
        updated = e.get("updated", "") or e.get("created", "")
        if updated and updated < cutoff:
            continue
        kept.append(e)
    if len(kept) > _SHORT_TERM_MAX:
        kept.sort(key=lambda e: e.get("updated", "") or e.get("created", ""))
        kept = kept[-_SHORT_TERM_MAX:]
    return kept


def _spawn_embed(layer: str, entry_id: str) -> None:
    """Compute and persist an embedding off the main thread (fire-and-forget).

    After embedding, if a semantically-duplicate entry already exists in the
    same layer (same meaning, different wording), the newer entry is merged into
    it — so near-duplicates are collapsed even when lexical dedup misses them.
    """
    def _work() -> None:
        try:
            with _lock:
                entries = _load(layer)
                entry = next((e for e in entries if e.get("id") == entry_id), None)
                if entry is None or entry.get("embedding"):
                    return
                content = entry.get("content", "")
            vec = embed(content)
            if not vec:
                return
            with _lock:
                entries = _load(layer)
                entry = next((e for e in entries if e.get("id") == entry_id), None)
                if entry is None or entry.get("embedding"):
                    return
                entries = _semantic_merge(entries, entry, vec)
                _save(layer, entries)
        except Exception as e:
            print(f"[LayeredMemory] ⚠️ background embed error: {e}")

    t = threading.Thread(target=_work, daemon=True)
    t.start()


def _semantic_merge(entries: list[dict], entry: dict, vec: list[float]) -> list[dict]:
    """Attach ``vec`` to ``entry`` and collapse a semantic duplicate if one exists.

    Returns the updated entry list (caller saves). If a semantically-identical
    entry (same meaning, different wording) is found, the newer content wins and
    the duplicate is dropped; otherwise the embedding is simply stored.
    """
    entry["embedding"] = vec
    target = None
    for e in entries:
        if e.get("id") == entry.get("id"):
            continue
        if e.get("embedding") and _cosine(vec, e["embedding"]) >= _SEM_DUP_THRESHOLD:
            target = e
            break
    if target is None:
        return entries
    # Newer content wins (outdated-info correction); keep the surviving entry's id.
    target["content"] = entry.get("content", target.get("content"))
    target["labels"] = sorted(set(target.get("labels", []) + entry.get("labels", [])))
    target["importance"] = max(target.get("importance", 0.0), entry.get("importance", 0.0))
    target["updated"] = _now()
    target["embedding"] = vec
    return [e for e in entries if e.get("id") != entry.get("id")]


# ── Public read / retrieval API ────────────────────────────────────────────────

def search(query: str, layers: list[str] | tuple[str, ...] | str | None = None,
           top_k: int = 5, min_score: float = 0.0) -> list[dict]:
    """
    Semantic/lexical search across layers. Returns entries ranked by relevance.

    Each result is the stored entry dict plus a ``score`` and ``layer`` key.
    """
    query = (query or "").strip()
    if not query:
        return []
    resolved = _resolve_layers(layers)
    query_embedding = embed(query) if _get_client() else None

    scored: list[dict] = []
    with _lock:
        for layer in resolved:
            for entry in _load(layer):
                score = _entry_score(entry, query_embedding, query)
                if score < min_score:
                    continue
                result = dict(entry)
                result["layer"] = layer
                result["score"] = round(score, 4)
                scored.append(result)

    def _rank_key(r: dict) -> tuple:
        return (r.get("score", 0.0), r.get("importance", 0.0), r.get("updated", ""))

    scored.sort(key=_rank_key, reverse=True)
    return scored[:top_k]


def recall(query: str, layers=None, top_k: int = 5) -> str:
    """Return search results formatted as natural text for the model."""
    results = search(query, layers=layers, top_k=top_k)
    if not results:
        return f"No stored memories match: {query!r}"
    lines = [f"Memories relevant to {query!r}:"]
    for i, r in enumerate(results, 1):
        meta = f"[{r.get('layer')}]"
        if r.get("labels"):
            meta += f" tags={', '.join(r['labels'])}"
        if r.get("date"):
            meta += f" date={r['date']}"
        lines.append(f"{i}. {meta} {r.get('content', '')}")
    return "\n".join(lines)


def forget(entry_id: str, layer: str | None = None) -> bool:
    """Remove an entry by id. Returns True if something was removed."""
    if not entry_id:
        return False
    targets = _resolve_layers(layer)
    removed = False
    with _lock:
        for lyr in targets:
            entries = _load(lyr)
            before = len(entries)
            entries = [e for e in entries if e.get("id") != entry_id]
            if len(entries) != before:
                _save(lyr, entries)
                removed = True
    return removed


def get_layer(layer: str) -> list[dict]:
    with _lock:
        return _load(layer)


def clear_layer(layer: str) -> int:
    with _lock:
        entries = _load(layer)
        count = len(entries)
        _save(layer, [])
    return count


def all_entries(layers=None) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    with _lock:
        for layer in _resolve_layers(layers):
            result[layer] = _load(layer)
    return result


def consolidate(layer: str | None = None, threshold: float = _SEM_DUP_THRESHOLD) -> int:
    """
    Merge semantically-duplicate entries (same meaning, different wording).

    Only meaningful when entries have embeddings. Returns the number merged.
    """
    merged_count = 0
    with _lock:
        for lyr in _resolve_layers(layer):
            entries = _load(lyr)
            kept: list[dict] = []
            for e in entries:
                dup = None
                if e.get("embedding"):
                    for k in kept:
                        if k.get("embedding") and _cosine(e["embedding"], k["embedding"]) >= threshold:
                            dup = k
                            break
                if dup is not None:
                    dup["labels"] = sorted(set(dup.get("labels", []) + e.get("labels", [])))
                    dup["importance"] = max(dup.get("importance", 0.0), e.get("importance", 0.0))
                    dup["updated"] = _now()
                    merged_count += 1
                else:
                    kept.append(e)
            _save(lyr, kept)
    return merged_count


# ── Layer auto-detection heuristic ─────────────────────────────────────────────

_PROJECT_HINTS = (
    "project", "code", "error", "bug", "fix", "fixed", "config", "configuration",
    "install", "dependency", "python", "node", "npm", "pip", "database", "api",
    "module", "function", "build", "deploy", "deployment", "git", "repo", "sdk",
    "react", "frontend", "backend", "javascript", "typescript", "java", "rust",
    "docker", "kubernetes", "server", "framework", "library", "debug", "ide",
    "file",
)
_EPISODIC_HINTS = (
    "yesterday", "last week", "session", "task", "finished", "completed", "did",
    "changed", "change", "decided", "decision", "event", "happened",
)
_SHORT_HINTS = ("now", "currently", "today", "right now", "active task", "doing")

_WORD_RE_CACHE: dict[str, "re.Pattern"] = {}


def _hint_matches(hint: str, text: str) -> bool:
    """Match a single hint against text.

    Multi-word phrases use plain substring matching; single-word hints use
    word-boundary matching so short tokens (e.g. 'repo', 'api', 'did', 'now')
    don't false-positive inside longer words ('report', 'rapid', 'candidate',
    'snow').
    """
    if " " in hint:
        return hint in text
    if hint not in _WORD_RE_CACHE:
        _WORD_RE_CACHE[hint] = re.compile(r"\b" + re.escape(hint) + r"\b")
    return _WORD_RE_CACHE[hint].search(text) is not None


def _any_hint(hints, text: str) -> bool:
    return any(_hint_matches(h, text) for h in hints)


def guess_layer(content: str) -> str:
    """Best-effort layer classification for free-form memory content.

    Priority order reflects how explicit the temporal signal is:
      1. short_term — explicit "now / currently / today" markers
      2. episodic   — past-event markers (yesterday, finished, decided, …)
      3. project    — technical markers
      4. long_term  — default
    """
    text = (content or "").lower()
    if _any_hint(_SHORT_HINTS, text):
        return SHORT_TERM
    if _any_hint(_EPISODIC_HINTS, text):
        return EPISODIC
    if _any_hint(_PROJECT_HINTS, text):
        return PROJECT
    return LONG_TERM


# ── Prompt context formatting ──────────────────────────────────────────────────

def _resolve_layers(layers) -> list[str]:
    if not layers:
        return list(LAYERS)
    if isinstance(layers, str):
        layers = [layers]
    resolved = []
    for l in layers:
        if l in LAYERS and l not in resolved:
            resolved.append(l)
    return resolved or list(LAYERS)


def _fmt_entries(entries: list[dict], limit: int) -> list[str]:
    lines = []
    for e in entries[:limit]:
        text = e.get("content", "")
        if text:
            lines.append(f"  - {text}")
    return lines


def format_context(top_short: int = 4, top_long: int = 6, top_project: int = 6,
                   top_episodic: int = 4, max_chars: int = 1800) -> str:
    """
    Build a compact, prompt-safe snapshot of the layered store for system
    injection. Layers are ordered by recency (updated) within each section.
    """
    def _recent(lyr: str, n: int) -> list[dict]:
        entries = get_layer(lyr)
        entries.sort(key=lambda e: (e.get("importance", 0.0), e.get("updated", "")), reverse=True)
        return entries[:n]

    sections = [
        ("Recent / active (short-term)", _recent(SHORT_TERM, top_short)),
        ("Long-term (preferences, habits, facts)", _recent(LONG_TERM, top_long)),
        ("Projects / technical", _recent(PROJECT, top_project)),
        ("Past sessions / events", _recent(EPISODIC, top_episodic)),
    ]

    lines: list[str] = ["[STRUCTURED MEMORY — use naturally, never recite like a list]"]
    for title, entries in sections:
        if not entries:
            continue
        lines.append(f"{title}:")
        lines.extend(_fmt_entries(entries, 999))
    if len(lines) == 1:
        return ""

    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[: max_chars - 1].rstrip() + "…"
    return result + "\n"


# ── Session / episodic convenience ─────────────────────────────────────────────

def record_session(summary: str, language: str = "") -> dict:
    """Persist an end-of-session summary to the episodic layer."""
    return add_memory(
        content=summary,
        layer=EPISODIC,
        labels=["session"] + (["language"] if language else []),
        kind="session",
        date=datetime.now().strftime("%Y-%m-%d"),
        source="auto",
    )


def record_event(content: str, kind: str = "event", labels: list[str] | None = None) -> dict:
    """Persist an episodic event / completed task / change."""
    return add_memory(
        content=content,
        layer=EPISODIC,
        labels=labels,
        kind=kind,
        date=datetime.now().strftime("%Y-%m-%d"),
        source="auto",
    )
