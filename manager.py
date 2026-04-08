"""
ASRManager — selects the correct backend based on settings.asr.backend
and implements automatic fallback (NIM → local) when a backend fails.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from voiceflow.asr.base import BaseASR
from voiceflow.asr.local import LocalASR
from voiceflow.asr.nim import NIMASR

if TYPE_CHECKING:
    from voiceflow.config.settings import Settings

log = logging.getLogger(__name__)


class ASRManager:
    """
    Facade over LocalASR and NIMASR.

    backend = "local"  → always use LocalASR
    backend = "nim"    → always use NIMASR (raises if unavailable)
    backend = "auto"   → prefer LocalASR, fall back to NIMASR
    """

    def __init__(self, settings: "Settings") -> None:
        self.settings = settings
        self._local: LocalASR | None = None
        self._nim: NIMASR | None = None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def preload(self) -> None:
        backend = self.settings.asr.backend
        if backend in ("local", "auto"):
            self._get_local().preload()
        if backend in ("nim", "auto"):
            self._get_nim().preload()

    def transcribe(self, audio_bytes: bytes) -> str:
        backend = self.settings.asr.backend

        if backend == "local":
            return self._get_local().transcribe(audio_bytes)

        if backend == "nim":
            return self._get_nim().transcribe(audio_bytes)

        # "auto" mode: try local first, fall back to NIM
        try:
            return self._get_local().transcribe(audio_bytes)
        except Exception as local_exc:
            log.warning("Local ASR failed (%s) — trying NIM", local_exc)
            try:
                return self._get_nim().transcribe(audio_bytes)
            except Exception as nim_exc:
                raise RuntimeError(
                    f"Both ASR backends failed. "
                    f"Local: {local_exc}. NIM: {nim_exc}"
                ) from nim_exc

    # ------------------------------------------------------------------
    # Lazy backend accessors
    # ------------------------------------------------------------------

    def _get_local(self) -> LocalASR:
        if self._local is None:
            self._local = LocalASR(self.settings)
        return self._local

    def _get_nim(self) -> NIMASR:
        if self._nim is None:
            self._nim = NIMASR(self.settings)
        return self._nim
