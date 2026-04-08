"""
VoiceFlowCore — wires audio capture, VAD, ASR, polish, injection and hotkeys together.
All heavy work runs in daemon threads; the main thread stays free for the Tkinter orb.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from enum import Enum, auto
from typing import TYPE_CHECKING

from voiceflow.audio.capture import AudioCapture
from voiceflow.asr.manager import ASRManager
from voiceflow.hotkeys.manager import HotkeyManager
from voiceflow.inject.typer import TextTyper
from voiceflow.polish.llm import LLMPolish

if TYPE_CHECKING:
    from voiceflow.config.settings import Settings
    from voiceflow.ui.orb import OrbWindow

log = logging.getLogger(__name__)


class AppState(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    DONE = auto()
    ERROR = auto()


class VoiceFlowCore:
    """Central coordinator for all VoiceFlow components."""

    def __init__(self, settings: "Settings", orb: "OrbWindow") -> None:
        self.settings = settings
        self.orb = orb
        self._stop_event = threading.Event()
        self._state = AppState.IDLE

        # Component instances
        self.capture = AudioCapture(settings)
        self.asr = ASRManager(settings)
        self.typer = TextTyper(settings)
        self.polish = LLMPolish(settings)
        self.hotkeys = HotkeyManager(settings, callbacks={
            "toggle":          self._on_toggle,
            "push_to_talk":    self._on_push_to_talk,
            "switch_backend":  self._on_switch_backend,
            "quit":            self._on_quit,
        })

        # Inter-thread communication
        self._audio_queue: queue.Queue[bytes | None] = queue.Queue()
        self._recording = threading.Event()
        self._push_to_talk_held = threading.Event()

        # Toggle state
        self._is_toggled_on = False

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start all background workers. Blocks until stop() is called."""
        log.info("Core starting…")

        # Pre-load the ASR model in the background so first use is snappy
        model_thread = threading.Thread(
            target=self._preload_model, daemon=True, name="model-preload"
        )
        model_thread.start()

        # Audio worker
        audio_thread = threading.Thread(
            target=self._audio_worker, daemon=True, name="audio"
        )
        audio_thread.start()

        # Hotkey listener
        self.hotkeys.start()

        log.info("Core running — press %s to start dictating",
                 self.settings.hotkeys.toggle)

        self._stop_event.wait()
        log.info("Core stopping…")

    def stop(self) -> None:
        self._stop_event.set()
        self.hotkeys.stop()
        self.capture.stop()

    # ------------------------------------------------------------------
    # Hotkey callbacks  (called from the pynput listener thread)
    # ------------------------------------------------------------------

    def _on_toggle(self) -> None:
        if self._state == AppState.LISTENING:
            self._stop_recording()
        else:
            self._start_recording()

    def _on_push_to_talk(self, pressed: bool) -> None:
        if pressed and self._state == AppState.IDLE:
            self._start_recording()
            self._push_to_talk_held.set()
        elif not pressed and self._push_to_talk_held.is_set():
            self._push_to_talk_held.clear()
            self._stop_recording()

    def _on_switch_backend(self) -> None:
        backends = ["local", "nim", "auto"]
        current = self.settings.asr.backend
        idx = backends.index(current) if current in backends else 0
        new = backends[(idx + 1) % len(backends)]
        self.settings.asr.backend = new
        log.info("Switched ASR backend → %s", new)
        self.orb.show_toast(f"Backend: {new.upper()}")

    def _on_quit(self) -> None:
        log.info("Quit hotkey pressed")
        self.stop()
        self.orb.quit()

    # ------------------------------------------------------------------
    # Recording control
    # ------------------------------------------------------------------

    def _start_recording(self) -> None:
        if self._state != AppState.IDLE:
            return
        log.debug("Recording started")
        self._set_state(AppState.LISTENING)
        self._recording.set()

    def _stop_recording(self) -> None:
        if self._state != AppState.LISTENING:
            return
        log.debug("Recording stopped by user")
        self._recording.clear()
        # Sentinel to flush the audio worker
        self._audio_queue.put(None)

    # ------------------------------------------------------------------
    # Audio worker — runs in its own thread
    # ------------------------------------------------------------------

    def _audio_worker(self) -> None:
        """
        Waits for _recording event, collects VAD-gated audio frames,
        then dispatches to ASR+inject pipeline.
        """
        while not self._stop_event.is_set():
            # Block until recording is requested
            self._recording.wait(timeout=0.1)
            if not self._recording.is_set():
                continue

            log.debug("Audio worker: collecting audio…")
            audio_bytes = self._collect_audio()

            if audio_bytes and len(audio_bytes) > 3200:  # at least 100ms
                self._set_state(AppState.PROCESSING)
                self._process_audio(audio_bytes)
            else:
                self._set_state(AppState.IDLE)

    def _collect_audio(self) -> bytes:
        """Stream mic audio until silence or stop signal, return raw PCM bytes."""
        frames: list[bytes] = []
        silence_ms = 0
        max_ms = self.settings.audio.max_recording * 1000
        elapsed_ms = 0
        silence_limit_ms = int(self.settings.audio.silence_duration * 1000)

        for chunk in self.capture.stream():
            if not self._recording.is_set() or self._stop_event.is_set():
                break
            if chunk is None:
                break

            frames.append(chunk.raw_pcm)
            elapsed_ms += self.settings.audio.chunk_ms

            if chunk.is_speech:
                silence_ms = 0
            else:
                silence_ms += self.settings.audio.chunk_ms

            if silence_ms >= silence_limit_ms:
                log.debug("VAD silence threshold reached — ending recording")
                break

            if elapsed_ms >= max_ms:
                log.warning("Max recording duration reached")
                break

        self._recording.clear()
        return b"".join(frames)

    # ------------------------------------------------------------------
    # ASR + Polish + Inject pipeline
    # ------------------------------------------------------------------

    def _process_audio(self, audio_bytes: bytes) -> None:
        try:
            text = self.asr.transcribe(audio_bytes)
            log.info("Transcript: %r", text)

            if not text or not text.strip():
                self._set_state(AppState.IDLE)
                return

            # Optional LLM polish
            if self.settings.polish.enabled:
                text = self.polish.refine(text)
                log.info("Polished: %r", text)

            # Handle built-in voice commands
            text = self._apply_voice_commands(text)

            if text:
                self.typer.type_text(text)
                word_count = len(text.split())
                self._set_state(AppState.DONE)
                self.orb.show_toast(f"✓ {word_count} word{'s' if word_count != 1 else ''}")
            else:
                self._set_state(AppState.IDLE)

        except Exception as exc:
            log.error("Pipeline error: %s", exc, exc_info=True)
            self._set_state(AppState.ERROR)
            self.orb.show_toast("⚠ Error — check logs")
        finally:
            # Return to idle after a brief display of DONE/ERROR
            def _reset():
                time.sleep(1.5)
                self._set_state(AppState.IDLE)
            threading.Thread(target=_reset, daemon=True).start()

    # ------------------------------------------------------------------
    # Voice commands (no AI needed)
    # ------------------------------------------------------------------

    VOICE_COMMANDS: dict[str, str] = {
        "new line":       "\n",
        "new paragraph":  "\n\n",
        "period":         ".",
        "full stop":      ".",
        "comma":          ",",
        "exclamation":    "!",
        "question mark":  "?",
        "colon":          ":",
        "semicolon":      ";",
        "open paren":     "(",
        "close paren":    ")",
        "open bracket":   "[",
        "close bracket":  "]",
        "tab":            "\t",
        "delete that":    "__DELETE__",
        "cancel":         "__CANCEL__",
    }

    def _apply_voice_commands(self, text: str) -> str | None:
        lower = text.lower().strip().rstrip(".")
        if lower in self.VOICE_COMMANDS:
            action = self.VOICE_COMMANDS[lower]
            if action == "__CANCEL__":
                return None
            if action == "__DELETE__":
                # Undo the last typed text using Ctrl+Z
                self.typer.undo()
                return None
            return action
        # Inline substitution
        for phrase, replacement in self.VOICE_COMMANDS.items():
            if replacement in ("\n", "\n\n", ".", ",", "!", "?"):
                text = text.replace(f" {phrase}", replacement)
        return text

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def _set_state(self, state: AppState) -> None:
        self._state = state
        self.orb.set_state(state.name.lower())
        log.debug("State → %s", state.name)

    def _preload_model(self) -> None:
        """Eagerly load the ASR model so first dictation has no cold-start."""
        try:
            self.asr.preload()
            log.info("ASR model preloaded ✓")
        except Exception as exc:
            log.warning("Model preload failed (will load on first use): %s", exc)
