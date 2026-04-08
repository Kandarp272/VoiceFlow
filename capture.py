"""
AudioCapture — streams microphone audio in VAD-gated chunks using sounddevice.
Each yielded AudioChunk contains raw PCM bytes and a VAD speech flag.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Generator, TYPE_CHECKING

import numpy as np
import sounddevice as sd

from voiceflow.audio.vad import VADFilter

if TYPE_CHECKING:
    from voiceflow.config.settings import Settings

log = logging.getLogger(__name__)


@dataclass
class AudioChunk:
    raw_pcm: bytes       # 16-bit signed PCM, mono, 16kHz
    is_speech: bool      # VAD decision for this chunk
    rms: float           # RMS energy (for UI level meter)


class AudioCapture:
    """
    Captures microphone audio and streams AudioChunk objects via a generator.
    Uses sounddevice for cross-platform WASAPI/ALSA/CoreAudio support.
    """

    def __init__(self, settings: "Settings") -> None:
        self.settings = settings
        self._sr = settings.audio.sample_rate
        self._channels = settings.audio.channels
        self._chunk_ms = settings.audio.chunk_ms
        self._chunk_frames = int(self._sr * self._chunk_ms / 1000)

        self._vad = VADFilter(
            aggressiveness=settings.audio.vad_aggressiveness,
            sample_rate=self._sr,
        )

        self._audio_q: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=100)
        self._stream: sd.InputStream | None = None
        self._running = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def stream(self) -> Generator[AudioChunk, None, None]:
        """
        Start the mic and yield AudioChunk objects until stop() is called
        or the queue receives a None sentinel.
        """
        self._start_stream()
        try:
            while True:
                try:
                    frame = self._audio_q.get(timeout=0.5)
                except queue.Empty:
                    if not self._running.is_set():
                        break
                    continue

                if frame is None:
                    break

                pcm_bytes = (frame * 32767).astype(np.int16).tobytes()
                is_speech = self._vad.is_speech(pcm_bytes)
                rms = float(np.sqrt(np.mean(frame ** 2)))

                yield AudioChunk(raw_pcm=pcm_bytes, is_speech=is_speech, rms=rms)
        finally:
            self._stop_stream()

    def stop(self) -> None:
        self._running.clear()
        self._audio_q.put(None)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _start_stream(self) -> None:
        self._running.set()
        # Flush stale frames
        while not self._audio_q.empty():
            try:
                self._audio_q.get_nowait()
            except queue.Empty:
                break

        self._stream = sd.InputStream(
            samplerate=self._sr,
            channels=self._channels,
            dtype="float32",
            blocksize=self._chunk_frames,
            callback=self._sd_callback,
        )
        self._stream.start()
        log.debug(
            "Audio stream started — sr=%d chunk_ms=%d", self._sr, self._chunk_ms
        )

    def _stop_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                log.debug("Stream close error: %s", exc)
            self._stream = None
        log.debug("Audio stream stopped")

    def _sd_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            log.warning("sounddevice status: %s", status)
        if self._running.is_set():
            try:
                self._audio_q.put_nowait(indata[:, 0].copy())
            except queue.Full:
                log.warning("Audio queue full — dropping frame")
