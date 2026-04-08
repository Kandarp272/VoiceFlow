"""Base interface that all ASR backends must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseASR(ABC):
    """Abstract ASR backend."""

    @abstractmethod
    def transcribe(self, audio_bytes: bytes) -> str:
        """
        Transcribe raw 16-bit PCM mono 16kHz audio bytes.
        Returns the transcribed text string.
        """

    def preload(self) -> None:
        """Optional: eagerly load the model/connection."""
