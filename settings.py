"""
Settings — loads config.yaml, provides typed dataclass access,
and supports live mutation (e.g. switching backend at runtime).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Typed config dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LocalASRConfig:
    model: str = "small"
    compute_type: str = "auto"
    device: str = "auto"


@dataclass
class NIMASRConfig:
    api_key: str = ""
    endpoint: str = "https://integrate.api.nvidia.com/v1"
    model: str = "nvidia/parakeet-tdt-1.1b"
    timeout: int = 10


@dataclass
class ASRConfig:
    backend: Literal["local", "nim", "auto"] = "local"
    local: LocalASRConfig = field(default_factory=LocalASRConfig)
    nim: NIMASRConfig = field(default_factory=NIMASRConfig)


@dataclass
class HotkeyConfig:
    toggle: str = "<alt>+<space>"
    push_to_talk: str = "<alt>+<shift>+<space>"
    switch_backend: str = "<ctrl>+<alt>+b"
    quit: str = "<ctrl>+<alt>+q"


@dataclass
class InjectionConfig:
    method: Literal["clipboard", "type"] = "clipboard"
    restore_clipboard: bool = True
    paste_delay: float = 0.05


@dataclass
class OllamaPolishConfig:
    endpoint: str = "http://localhost:11434"
    model: str = "llama3.2"


@dataclass
class OpenRouterPolishConfig:
    api_key: str = ""
    model: str = "qwen/qwen-2.5-7b-instruct:free"


@dataclass
class NIMPolishConfig:
    api_key: str = ""
    model: str = "meta/llama-3.1-8b-instruct"


@dataclass
class PolishConfig:
    enabled: bool = False
    backend: Literal["ollama", "openrouter", "nim"] = "ollama"
    ollama: OllamaPolishConfig = field(default_factory=OllamaPolishConfig)
    openrouter: OpenRouterPolishConfig = field(default_factory=OpenRouterPolishConfig)
    nim: NIMPolishConfig = field(default_factory=NIMPolishConfig)
    system_prompt: str = (
        "You are a transcription editor. Fix grammar and punctuation. "
        "Remove filler words (um, uh, like). Apply formatting commands "
        "(e.g. 'new paragraph' → newline). Return only the corrected text."
    )


@dataclass
class OrbConfig:
    size: int = 64
    position: Literal["bottom-right", "bottom-left", "top-right", "top-left"] = (
        "bottom-right"
    )
    margin: int = 24
    opacity: float = 0.95


@dataclass
class UIConfig:
    orb: OrbConfig = field(default_factory=OrbConfig)


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    chunk_ms: int = 30
    vad_aggressiveness: int = 2
    silence_duration: float = 0.6
    max_recording: int = 30


# ---------------------------------------------------------------------------
# Settings loader
# ---------------------------------------------------------------------------


def _merge(base: dict, override: dict) -> dict:
    """Deep-merge override into base."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _merge(result[k], v)
        else:
            result[k] = v
    return result


class Settings:
    """Loads and exposes typed configuration. Supports live mutation."""

    _DEFAULTS: dict = {
        "asr": {
            "backend": "local",
            "local": {"model": "small", "compute_type": "auto", "device": "auto"},
            "nim": {
                "api_key": "",
                "endpoint": "https://integrate.api.nvidia.com/v1",
                "model": "nvidia/parakeet-tdt-1.1b",
                "timeout": 10,
            },
        },
        "hotkeys": {
            "toggle": "<alt>+<space>",
            "push_to_talk": "<alt>+<shift>+<space>",
            "switch_backend": "<ctrl>+<alt>+b",
            "quit": "<ctrl>+<alt>+q",
        },
        "injection": {
            "method": "clipboard",
            "restore_clipboard": True,
            "paste_delay": 0.05,
        },
        "polish": {
            "enabled": False,
            "backend": "ollama",
            "ollama": {"endpoint": "http://localhost:11434", "model": "llama3.2"},
            "openrouter": {"api_key": "", "model": "qwen/qwen-2.5-7b-instruct:free"},
            "nim": {"api_key": "", "model": "meta/llama-3.1-8b-instruct"},
        },
        "ui": {
            "orb": {
                "size": 64,
                "position": "bottom-right",
                "margin": 24,
                "opacity": 0.95,
            }
        },
        "audio": {
            "sample_rate": 16000,
            "channels": 1,
            "chunk_ms": 30,
            "vad_aggressiveness": 2,
            "silence_duration": 0.6,
            "max_recording": 30,
        },
    }

    def __init__(self, config_path: str = "config.yaml") -> None:
        raw = dict(self._DEFAULTS)

        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                user_cfg = yaml.safe_load(f) or {}
            raw = _merge(raw, user_cfg)
            log.debug("Loaded config from %s", path)
        else:
            log.info("Config file not found at %s — using defaults", path)

        # Environment variable overrides
        if key := os.environ.get("VOICEFLOW_NIM_API_KEY"):
            raw["asr"]["nim"]["api_key"] = key
            raw["polish"]["nim"]["api_key"] = key
        if key := os.environ.get("VOICEFLOW_OPENROUTER_API_KEY"):
            raw["polish"]["openrouter"]["api_key"] = key

        # Build typed sub-configs
        a = raw["asr"]
        self.asr = ASRConfig(
            backend=a["backend"],
            local=LocalASRConfig(**a["local"]),
            nim=NIMASRConfig(**a["nim"]),
        )

        hk = raw["hotkeys"]
        self.hotkeys = HotkeyConfig(**hk)

        inj = raw["injection"]
        self.injection = InjectionConfig(**inj)

        p = raw["polish"]
        self.polish = PolishConfig(
            enabled=p["enabled"],
            backend=p["backend"],
            ollama=OllamaPolishConfig(**p["ollama"]),
            openrouter=OpenRouterPolishConfig(**p["openrouter"]),
            nim=NIMPolishConfig(**p["nim"]),
        )

        u = raw["ui"]
        self.ui = UIConfig(orb=OrbConfig(**u["orb"]))

        au = raw["audio"]
        self.audio = AudioConfig(**au)
