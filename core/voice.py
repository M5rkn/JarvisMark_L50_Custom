# -*- coding: utf-8 -*-
"""
Voice-pipeline decision logic for JARVIS — stdlib-only and offline-testable.

This module owns the *decisions* made inside the audio loop (voice state names,
end-of-speech detection, barge-in detection, duplicate-command suppression) so
they can be unit-tested without a microphone, speaker, Gemini session, or PyQt.
The actual audio I/O and Gemini wiring live in ``main.py``.

The states model a single spoken exchange:

    IDLE → LISTENING → PROCESSING → SPEAKING → IDLE
                         │                     ▲
                         └── INTERRUPTED ──────┘   (user barged in / interrupted)

  * IDLE        — connected, mic armed, waiting for the user
  * LISTENING   — local VAD is hearing a live utterance
  * PROCESSING  — model thinking / tool executing
  * SPEAKING    — TTS audio is playing
  * INTERRUPTED — user talked over TTS / pressed interrupt; mic re-opens immediately
  * SLEEPING    — disconnected / reconnecting
  * MUTED       — microphone muted
  * INITIALISING— app starting

Import-safe: stdlib only at import time.
"""

from __future__ import annotations

# ── Voice states ──────────────────────────────────────────────────────────────
INITIALISING = "INITIALISING"
IDLE         = "IDLE"
LISTENING    = "LISTENING"
PROCESSING   = "PROCESSING"
SPEAKING     = "SPEAKING"
INTERRUPTED  = "INTERRUPTED"
SLEEPING     = "SLEEPING"
MUTED        = "MUTED"

VOICE_STATES = (
    INITIALISING, IDLE, LISTENING, PROCESSING,
    SPEAKING, INTERRUPTED, SLEEPING, MUTED,
)


# ── End-of-speech detection ───────────────────────────────────────────────────
# seconds of silence that mark the end of a user utterance
END_OF_SPEECH_SILENCE = 1.2
# minimum elapsed time from the onset of a burst before end-of-speech may fire
# (a safety gate for the very start of a burst; kept ≪ the silence threshold so
# short one-word commands like "yes"/"ok" are never missed)
MIN_SPEECH_SECONDS = 0.3
# RMS threshold (int16 → float32 scale) above which a block counts as speech
SPEECH_RMS_THRESHOLD = 500.0


class EndOfSpeechDetector:
    """Detect the end of a user utterance from a stream of RMS values.

    Per speech burst the state is:

        idle --speech--> active --silence >= END_OF_SPEECH_SILENCE--> ended

    :meth:`update` returns ``"onset"`` once when a new burst starts, ``"eos"``
    once when a burst ends (only after ``min_speech`` seconds of speech), and
    ``None`` otherwise. After ``"eos"`` the detector goes quiet until the next
    burst (it does not re-fire for the same burst).
    """

    def __init__(self, *, silence: float = END_OF_SPEECH_SILENCE,
                 min_speech: float = MIN_SPEECH_SECONDS,
                 threshold: float = SPEECH_RMS_THRESHOLD):
        self.silence    = silence
        self.min_speech = min_speech
        self.threshold  = threshold
        self.reset()

    def reset(self) -> None:
        self.active       = False
        self.last_speech  = 0.0
        self.speech_start = 0.0
        self.eos_sent     = False

    def update(self, rms: float, now: float):
        """Feed one RMS sample. Returns ``"onset"``, ``"eos"``, or ``None``."""
        if rms > self.threshold:
            onset = not self.active
            if onset:
                self.speech_start = now
            self.last_speech  = now
            self.active       = True
            self.eos_sent     = False
            return "onset" if onset else None

        # silence
        if (self.active and not self.eos_sent
                and (now - self.last_speech) >= self.silence
                and (now - self.speech_start) >= self.min_speech):
            self.eos_sent = True
            self.active   = False
            return "eos"
        return None


# ── Barge-in detection ────────────────────────────────────────────────────────
# While JARVIS is speaking we do NOT stream mic audio to Gemini (echo
# suppression), so the model cannot natively barge-in. Instead we keep running a
# local energy detector during TTS and stop playback ourselves when the user
# talks over it. To avoid mistaking JARVIS's own echo for the user, the detector
# learns a short echo baseline at the start of each speech segment and only fires
# on *sustained* energy clearly above that baseline.

BARGE_IN_ENABLED      = True
BARGE_BASELINE_FRAMES = 6       # audio blocks used to learn the echo baseline
BARGE_FACTOR          = 2.0     # trigger only when RMS exceeds baseline × this
BARGE_FLOOR           = 1200.0  # absolute floor, so near-silent echo never fires
BARGE_MIN_FRAMES      = 5       # consecutive loud blocks required (≈0.32s at 64ms)
BARGE_COOLDOWN        = 1.5     # seconds before barge-in may fire again


class BargeInDetector:
    """Echo-resistant "user is talking over TTS" detector.

    Feed it the same per-block RMS that the VAD uses, but only while JARVIS is
    speaking. The first ``baseline_frames`` samples are used to learn the echo
    level; after that, sustained energy above ``max(baseline × factor, floor)``
    triggers exactly once per utterance (guarded by a cooldown).
    """

    def __init__(self, *, baseline_frames: int = BARGE_BASELINE_FRAMES,
                 factor: float = BARGE_FACTOR, floor: float = BARGE_FLOOR,
                 min_frames: int = BARGE_MIN_FRAMES,
                 cooldown: float = BARGE_COOLDOWN):
        self.baseline_frames = baseline_frames
        self.factor          = factor
        self.floor           = floor
        self.min_frames      = min_frames
        self.cooldown        = cooldown
        self.reset()

    def reset(self) -> None:
        self._baseline  = None
        self._learn     = []
        self._sustain   = 0
        self._last_fire = -1e9

    def process(self, rms: float, now: float) -> bool:
        """Return ``True`` exactly once when a barge-in is detected."""
        # Learning phase: collect the echo baseline. Using the lower tercile
        # keeps the baseline low even if the user is already talking during the
        # first few blocks, so detection still works.
        if self._baseline is None:
            self._learn.append(rms)
            if len(self._learn) < self.baseline_frames:
                return False
            s = sorted(self._learn)
            self._baseline = s[max(0, len(s) // 3)]
            self._learn = None
            return False

        threshold = max(self._baseline * self.factor, self.floor)

        if rms >= threshold:
            self._sustain += 1
        else:
            # Require *sustained* loud speech — a single loud click must not
            # cut JARVIS off.
            self._sustain = max(0, self._sustain - 1)

        if self._sustain >= self.min_frames and (now - self._last_fire) >= self.cooldown:
            self._last_fire = now
            self._sustain   = 0
            return True
        return False


# ── Duplicate-command suppression ─────────────────────────────────────────────
TOOL_DEDUP_WINDOW = 2.5   # seconds within which an identical call is a duplicate


class DuplicateGuard:
    """Suppress an identical tool call repeated within a short window.

    A duplicate is only suppressed when *no new user speech* intervened since
    the last execution — that is what distinguishes "JARVIS heard its own TTS
    and re-issued the same call" (echo, suppress) from "the user genuinely asked
    for the same thing again" (allow).
    """

    def __init__(self, window: float = TOOL_DEDUP_WINDOW):
        self.window = window
        self.reset()

    def reset(self) -> None:
        self.last_sig         = None
        self.last_time        = 0.0
        self.last_tool_speech = 0.0

    def should_suppress(self, sig, now: float, last_user_speech: float) -> bool:
        """Return True if ``sig`` should be skipped as a duplicate."""
        is_dup = (
            self.last_sig == sig
            and (now - self.last_time) < self.window
            and last_user_speech <= self.last_tool_speech
        )
        if not is_dup:
            self.last_sig         = sig
            self.last_time        = now
            self.last_tool_speech = last_user_speech
        return is_dup
