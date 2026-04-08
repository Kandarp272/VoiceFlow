"""
LocalASR — uses faster-whisper (CTranslate2) for fully offline transcription.
Supports CUDA, CPU with INT8 quantization, and auto device selection.
"""

from __future__ import annotations

import io
import logging
import wave
from typing import TYPE_CHECKING

import numpy as np

from voiceflow.asr.base import BaseASR

if TYPE_CHECKING:
    from voiceflow.config.settings import Settings

log = logging.getLogger(__name__)


class LocalASR(BaseASR):
    """
    Offline ASR using faster-whisper.
    Model is lazy-loaded on first transcription call (or eagerly via preload()).
    """

    def __init__(self, settings: "Settings") -> None:
        self.cfg = settings.asr.local
        self._model = None
        self._model_lock = __import__("threading").Lock()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def preload(self) -> None:
        self._get_model()

    def transcribe(self, audio_bytes: bytes) -> str:
        """Transcribe raw 16-bit signed PCM mono 16kHz bytes."""
        model = self._get_model()

        # Convert raw PCM → float32 numpy array
        audio_np = (
            np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        )

        segments, info = model.transcribe(
            audio_np,
            beam_size=5,
            language=None,        # auto-detect
            condition_on_previous_text=False,
            vad_filter=True,      # faster-whisper built-in VAD (Silero)
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        text = " ".join(seg.text.strip() for seg in segments).strip()
        log.debug(
            "Local ASR: %r  [lang=%s prob=%.2f]",
            text,
            info.language,
            info.language_probability,
        )
        return text

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_model(self):
        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is not None:  # double-check
                return self._model

            device, compute_type = self._resolve_device_compute()
            log.info(
                "Loading faster-whisper model=%s device=%s compute=%s …",
                self.cfg.model,
                device,
                compute_type,
            )

            try:
                from faster_whisper import WhisperModel  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "faster-whisper not installed. Run: pip install faster-whisper"
                ) from exc

            self._model = WhisperModel(
                self.cfg.model,
                device=device,
                compute_type=compute_type,
                download_root=None,   # uses ~/.cache/huggingface
                num_workers=1,
            )
            log.info("faster-whisper model loaded ✓")
            return self._model

    def _resolve_device_compute(self) -> tuple[str, str]:
        device = self.cfg.device
        compute = self.cfg.compute_type

        if device == "auto":
            try:
                import torch  # type: ignore

                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        if compute == "auto":
            compute = "float16" if device == "cuda" else "int8"

        return device, compute
