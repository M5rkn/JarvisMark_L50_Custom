# -*- coding: utf-8 -*-
"""
Smoke test for the JARVIS multi-layer structured memory engine.

Runs WITHOUT the voice engine / Gemini / PyQt — it exercises only the layered
store (pure stdlib at import time) with embeddings disabled, so every check is
deterministic and offline. It verifies:

    * the four layers persist independently to memory/store/
    * add / update / dedup behaviour (no duplicate entries for the same fact)
    * outdated-content correction (newer fact overwrites, id + created kept)
    * semantic-style retrieval via the lexical fallback path
    * layer auto-detection, forget, and prompt-context formatting
    * short-term pruning cap

Run:  python memory/test_layered_memory.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import memory.layered_memory as lm


def _fresh_store(tmp: Path) -> None:
    lm._STORE_DIR = tmp / "store"
    lm._client = False               # no Gemini client — force lexical path
    lm.embed = lambda text: None     # deterministic, offline


def main() -> int:
    failures = 0

    def check(label, cond, extra=""):
        nonlocal failures
        status = "PASS" if cond else "FAIL"
        print(f"[{status}] {label}" + (f" — {extra}" if extra else ""))
        if not cond:
            failures += 1

    with tempfile.TemporaryDirectory() as tmp:
        _fresh_store(Path(tmp))

        # ── 1. add + persistence ─────────────────────────────────────────────
        r1 = lm.add_memory("User prefers dark mode", layer=lm.LONG_TERM,
                           labels=["preference"], embed_async=False)
        check("add_memory returns an id", bool(r1.get("id")), str(r1))

        # A fresh read must see it (survives the in-memory round trip)
        entries = lm.get_layer(lm.LONG_TERM)
        check("long_term layer persists one entry", len(entries) == 1, str(len(entries)))
        check("stored content matches", entries[0]["content"] == "User prefers dark mode")

        # ── 2. dedup: same fact again → merge, not duplicate ────────────────
        r2 = lm.add_memory("User prefers dark mode", layer=lm.LONG_TERM,
                           labels=["preference"], embed_async=False)
        entries = lm.get_layer(lm.LONG_TERM)
        check("duplicate add merges (merged=True)", r2.get("merged") is True, str(r2))
        check("no duplicate entry created", len(entries) == 1, str(len(entries)))

        # ── 3. outdated-info correction ─────────────────────────────────────
        before = entries[0]
        r3 = lm.add_memory("User prefers dark mode on all apps", layer=lm.LONG_TERM,
                           labels=["preference"], embed_async=False)
        after = lm.get_layer(lm.LONG_TERM)[0]
        check("update keeps the same id", after["id"] == before["id"])
        check("update keeps original created", after["created"] == before["created"])
        check("update refreshes content", after["content"] == "User prefers dark mode on all apps")
        check("update bumps updated timestamp", after["updated"] >= before["updated"])

        # ── 4. layer auto-detection ─────────────────────────────────────────
        check("project hint", lm.guess_layer("Fixed a bug in the database module") == lm.PROJECT)
        check("episodic hint", lm.guess_layer("Yesterday we finished the report") == lm.EPISODIC)
        check("short-term hint", lm.guess_layer("Currently doing the deploy") == lm.SHORT_TERM)
        check("default long-term", lm.guess_layer("Likes classical music") == lm.LONG_TERM)

        # ── 5. invalid layer coerces to long_term ───────────────────────────
        lm.add_memory("Some stray fact", layer="nonsense", embed_async=False)
        check("invalid layer falls back to long_term",
              any("Some stray fact" == e["content"] for e in lm.get_layer(lm.LONG_TERM)))

        # ── 6. retrieval via lexical fallback ───────────────────────────────
        lm.add_memory("The main project uses Python and PyQt6", layer=lm.PROJECT,
                      embed_async=False)
        lm.add_memory("User's birthday is March 3rd", layer=lm.LONG_TERM,
                      embed_async=False)
        results = lm.search("what language is the project written in", layers=[lm.PROJECT], top_k=1)
        check("search returns a result", len(results) >= 1)
        if results:
            check("search ranks the project entry first",
                  "Python" in results[0]["content"], results[0]["content"])

        recall_text = lm.recall("birthday", layers=[lm.LONG_TERM])
        check("recall returns formatted text", "March 3rd" in recall_text, recall_text)

        # ── 7. forget ───────────────────────────────────────────────────────
        lm.add_memory("Temporary thought", layer=lm.SHORT_TERM, embed_async=False)
        tmp_entry = next(e for e in lm.get_layer(lm.SHORT_TERM) if e["content"] == "Temporary thought")
        check("forget removes by id", lm.forget(tmp_entry["id"]) is True)
        check("forgot entry is gone",
              not any(e["id"] == tmp_entry["id"] for e in lm.get_layer(lm.SHORT_TERM)))

        # ── 8. prompt context formatting ────────────────────────────────────
        ctx = lm.format_context()
        check("format_context includes a stored fact", "User prefers dark mode" in ctx)
        check("format_context has the header", "[STRUCTURED MEMORY" in ctx)

        # ── 9. short-term pruning cap ───────────────────────────────────────
        for i in range(lm._SHORT_TERM_MAX + 5):
            lm.add_memory(f"active task {i}", layer=lm.SHORT_TERM, embed_async=False)
        st = lm.get_layer(lm.SHORT_TERM)
        check("short-term is capped", len(st) <= lm._SHORT_TERM_MAX, str(len(st)))

        # ── 10. empty store → empty context ────────────────────────────────
        lm.clear_layer(lm.LONG_TERM)
        lm.clear_layer(lm.PROJECT)
        lm.clear_layer(lm.SHORT_TERM)
        lm.clear_layer(lm.EPISODIC)
        check("empty store formats to empty string", lm.format_context() == "")

    print()
    if failures:
        print(f"{failures} check(s) FAILED")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
