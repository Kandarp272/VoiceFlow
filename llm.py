"""
LLMPolish — optionally refines raw ASR transcripts through an LLM.
Removes filler words, fixes grammar, applies spoken formatting commands.

Supported backends:
  ollama      — local Ollama server (zero cost, offline)
  openrouter  — OpenRouter free tier (Qwen, Gemma, Llama)
  nim         — NVIDIA NIM LLM endpoint
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from voiceflow.config.settings import Settings

log = logging.getLogger(__name__)

_TIMEOUT = 15  # seconds


class LLMPolish:
    """Post-processes ASR transcripts through a configurable LLM."""

    def __init__(self, settings: "Settings") -> None:
        self.cfg = settings.polish
        self.audio_cfg = settings.audio

    def refine(self, text: str) -> str:
        """
        Send raw transcript to LLM; return cleaned text.
        Returns original text on any error so dictation is never blocked.
        """
        if not self.cfg.enabled or not text.strip():
            return text

        backend = self.cfg.backend
        try:
            if backend == "ollama":
                return self._ollama(text)
            elif backend == "openrouter":
                return self._openrouter(text)
            elif backend == "nim":
                return self._nim(text)
            else:
                log.warning("Unknown polish backend: %s", backend)
                return text
        except Exception as exc:
            log.warning("LLM polish failed (%s) — returning raw transcript", exc)
            return text

    # ------------------------------------------------------------------
    # Backend implementations
    # ------------------------------------------------------------------

    def _ollama(self, text: str) -> str:
        url = f"{self.cfg.ollama.endpoint.rstrip('/')}/api/generate"
        payload = {
            "model": self.cfg.ollama.model,
            "prompt": self._build_prompt(text),
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 512},
        }
        resp = requests.post(url, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()["response"].strip()

    def _openrouter(self, text: str) -> str:
        if not self.cfg.openrouter.api_key:
            raise RuntimeError("OpenRouter API key not set")

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.cfg.openrouter.api_key}",
            "HTTP-Referer": "https://github.com/voiceflow",
            "X-Title": "VoiceFlow",
        }
        payload = {
            "model": self.cfg.openrouter.model,
            "messages": [
                {"role": "system", "content": self.cfg.system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
            "max_tokens": 512,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    def _nim(self, text: str) -> str:
        from voiceflow.config.settings import NIMPolishConfig
        cfg: NIMPolishConfig = self.cfg.nim

        if not cfg.api_key:
            raise RuntimeError("NIM LLM API key not set")

        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {cfg.api_key}"}
        payload = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": self.cfg.system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
            "max_tokens": 512,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    def _build_prompt(self, raw: str) -> str:
        """For Ollama (non-chat format)."""
        return (
            f"{self.cfg.system_prompt}\n\n"
            f"Raw transcript:\n{raw}\n\n"
            "Corrected text:"
        )
