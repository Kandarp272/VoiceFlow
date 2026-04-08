"""
NIMASR — transcribes audio via NVIDIA NIM hosted ASR endpoints.
Supports Parakeet-TDT-1.1B and Canary-1B.
Also supports self-hosted NIM (set endpoint to http://localhost:9000).
"""

from __future__ import annotations

import io
import logging
import struct
import wave
from typing import TYPE_CHECKING

import requests

from voiceflow.asr.base import BaseASR

if TYPE_CHECKING:
    from voiceflow.config.settings import Settings

log = logging.getLogger(__name__)

_TRANSCRIPTION_PATH = "/audio/transcriptions"


class NIMASR(BaseASR):
    """NVIDIA NIM ASR backend (REST API)."""

    def __init__(self, settings: "Settings") -> None:
        self.cfg = settings.asr.nim
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {self.cfg.api_key}"}
        )

    def preload(self) -> None:
        """Validate connectivity to NIM endpoint."""
        if not self.cfg.api_key:
            log.warning("NIM API key not set — NIM backend may fail")
            return
        try:
            url = self.cfg.endpoint.rstrip("/") + "/models"
            resp = self._session.get(url, timeout=5)
            resp.raise_for_status()
            log.info("NIM endpoint reachable ✓  (%s)", self.cfg.endpoint)
        except Exception as exc:
            log.warning("NIM preload check failed: %s", exc)

    def transcribe(self, audio_bytes: bytes) -> str:
        """
        Send raw 16-bit PCM mono 16kHz bytes to NIM ASR endpoint.
        Returns transcribed text.
        """
        if not self.cfg.api_key:
            raise RuntimeError(
                "NVIDIA NIM API key not set. "
                "Set VOICEFLOW_NIM_API_KEY env var or add to config.yaml"
            )

        wav_bytes = self._pcm_to_wav(audio_bytes)
        url = self.cfg.endpoint.rstrip("/") + _TRANSCRIPTION_PATH

        try:
            resp = self._session.post(
                url,
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data={"model": self.cfg.model},
                timeout=self.cfg.timeout,
            )
            resp.raise_for_status()
        except requests.Timeout:
            raise RuntimeError(
                f"NIM ASR timed out after {self.cfg.timeout}s"
            )
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"NIM ASR HTTP error {exc.response.status_code}: {exc.response.text}"
            ) from exc

        data = resp.json()
        text = data.get("text", "").strip()
        log.debug("NIM ASR: %r", text)
        return text

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
        """Wrap raw PCM in a WAV container."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)      # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        return buf.getvalue()
