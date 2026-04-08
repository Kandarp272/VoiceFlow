"""
Tests for VoiceFlow — configuration, VAD, ASR manager, text injection,
voice commands, and orb state management.

All tests that rely on system-level packages (PortAudio, tkinter, keyboard)
use mocks so the suite passes in headless CI environments.
"""

from __future__ import annotations

import io
import queue
import struct
import sys
import threading
import time
import types
import wave
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

# ---------------------------------------------------------------------------
# Stub out heavy system-level imports before any voiceflow module is loaded.
# This lets CI (no PortAudio / no tkinter / no keyboard) run the full suite.
# ---------------------------------------------------------------------------

def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod

# sounddevice stub (needs InputStream class)
if "sounddevice" not in sys.modules:
    sd_stub = _make_stub("sounddevice")
    sd_stub.InputStream = MagicMock
    sd_stub.CallbackFlags = MagicMock

# keyboard stub
if "keyboard" not in sys.modules:
    kb_stub = _make_stub("keyboard")
    kb_stub.write = MagicMock()
    kb_stub.send = MagicMock()

# tkinter stub (full enough for OrbWindow)
if "tkinter" not in sys.modules:
    tk_stub = _make_stub("tkinter")
    tk_stub.Tk = MagicMock
    tk_stub.Canvas = MagicMock
    tk_stub.StringVar = MagicMock

# pynput stub
if "pynput" not in sys.modules:
    pynput_stub = _make_stub("pynput")
    keyboard_mod = _make_stub("pynput.keyboard")
    keyboard_mod.GlobalHotKeys = MagicMock
    keyboard_mod.Listener = MagicMock
    pynput_stub.keyboard = keyboard_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_pcm(duration_ms: int = 300, sample_rate: int = 16000) -> bytes:
    """Generate silent 16-bit PCM audio."""
    n_samples = int(sample_rate * duration_ms / 1000)
    return struct.pack(f"<{n_samples}h", *([0] * n_samples))


def make_speech_pcm(duration_ms: int = 500, sample_rate: int = 16000) -> bytes:
    """Generate loud (speech-like) 16-bit PCM audio."""
    import math
    n_samples = int(sample_rate * duration_ms / 1000)
    samples = [int(16000 * math.sin(2 * math.pi * 440 * i / sample_rate)) for i in range(n_samples)]
    return struct.pack(f"<{n_samples}h", *samples)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class TestSettings:
    def test_defaults_load(self, tmp_path):
        from voiceflow.config.settings import Settings
        s = Settings(str(tmp_path / "nonexistent.yaml"))
        assert s.asr.backend == "local"
        assert s.asr.local.model == "small"
        assert s.hotkeys.toggle == "<alt>+<space>"
        assert s.injection.method == "clipboard"
        assert s.polish.enabled is False
        assert s.audio.sample_rate == 16000

    def test_yaml_override(self, tmp_path):
        from voiceflow.config.settings import Settings
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "asr:\n  backend: nim\n  local:\n    model: tiny\n"
        )
        s = Settings(str(cfg_file))
        assert s.asr.backend == "nim"
        assert s.asr.local.model == "tiny"
        # Non-overridden values keep defaults
        assert s.hotkeys.toggle == "<alt>+<space>"

    def test_env_overrides_api_key(self, tmp_path, monkeypatch):
        from voiceflow.config.settings import Settings
        monkeypatch.setenv("VOICEFLOW_NIM_API_KEY", "test-key-123")
        s = Settings(str(tmp_path / "nope.yaml"))
        assert s.asr.nim.api_key == "test-key-123"

    def test_partial_yaml_merges_defaults(self, tmp_path):
        from voiceflow.config.settings import Settings
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("polish:\n  enabled: true\n")
        s = Settings(str(cfg_file))
        assert s.polish.enabled is True
        assert s.polish.backend == "ollama"  # default preserved

    def test_runtime_mutation(self, tmp_path):
        from voiceflow.config.settings import Settings
        s = Settings(str(tmp_path / "nope.yaml"))
        s.asr.backend = "nim"
        assert s.asr.backend == "nim"


# ---------------------------------------------------------------------------
# VAD
# ---------------------------------------------------------------------------

class TestVAD:
    def test_energy_vad_silence(self):
        from voiceflow.audio.vad import VADFilter
        vad = VADFilter(aggressiveness=2, sample_rate=16000)
        # Override to use energy fallback
        vad._use_webrtcvad = False
        pcm = make_pcm(30)
        assert vad.is_speech(pcm) is False

    def test_energy_vad_speech(self):
        from voiceflow.audio.vad import VADFilter
        vad = VADFilter(aggressiveness=2, sample_rate=16000)
        vad._use_webrtcvad = False
        pcm = make_speech_pcm(30)
        assert vad.is_speech(pcm) is True

    def test_empty_pcm(self):
        from voiceflow.audio.vad import VADFilter
        vad = VADFilter()
        vad._use_webrtcvad = False
        assert vad.is_speech(b"") is False

    def test_invalid_sample_rate_raises(self):
        from voiceflow.audio.vad import VADFilter
        with pytest.raises(ValueError):
            VADFilter(sample_rate=22050)


# ---------------------------------------------------------------------------
# ASR Manager
# ---------------------------------------------------------------------------

class TestASRManager:
    def _make_settings(self, backend="local"):
        from voiceflow.config.settings import Settings
        import tempfile, os
        s = Settings(os.path.join(tempfile.gettempdir(), "nope.yaml"))
        s.asr.backend = backend
        return s

    def test_local_backend_calls_local_asr(self):
        from voiceflow.asr.manager import ASRManager
        s = self._make_settings("local")
        mgr = ASRManager(s)
        mock_local = MagicMock()
        mock_local.transcribe.return_value = "hello world"
        mgr._local = mock_local
        result = mgr.transcribe(make_pcm())
        assert result == "hello world"
        mock_local.transcribe.assert_called_once()

    def test_nim_backend_calls_nim_asr(self):
        from voiceflow.asr.manager import ASRManager
        s = self._make_settings("nim")
        mgr = ASRManager(s)
        mock_nim = MagicMock()
        mock_nim.transcribe.return_value = "nim result"
        mgr._nim = mock_nim
        result = mgr.transcribe(make_pcm())
        assert result == "nim result"

    def test_auto_falls_back_to_nim_when_local_fails(self):
        from voiceflow.asr.manager import ASRManager
        s = self._make_settings("auto")
        mgr = ASRManager(s)

        mock_local = MagicMock()
        mock_local.transcribe.side_effect = RuntimeError("GPU OOM")
        mock_nim = MagicMock()
        mock_nim.transcribe.return_value = "fallback"

        mgr._local = mock_local
        mgr._nim = mock_nim

        result = mgr.transcribe(make_pcm())
        assert result == "fallback"

    def test_auto_raises_when_both_fail(self):
        from voiceflow.asr.manager import ASRManager
        s = self._make_settings("auto")
        mgr = ASRManager(s)

        mock_local = MagicMock()
        mock_local.transcribe.side_effect = RuntimeError("local fail")
        mock_nim = MagicMock()
        mock_nim.transcribe.side_effect = RuntimeError("nim fail")

        mgr._local = mock_local
        mgr._nim = mock_nim

        with pytest.raises(RuntimeError, match="Both ASR backends failed"):
            mgr.transcribe(make_pcm())


# ---------------------------------------------------------------------------
# NIM ASR — unit (no network)
# ---------------------------------------------------------------------------

class TestNIMASR:
    def _make_settings(self):
        from voiceflow.config.settings import Settings
        import tempfile, os
        s = Settings(os.path.join(tempfile.gettempdir(), "nope.yaml"))
        s.asr.nim.api_key = "test-key"
        return s

    def test_missing_api_key_raises(self):
        from voiceflow.asr.nim import NIMASR
        from voiceflow.config.settings import Settings
        import tempfile, os
        s = Settings(os.path.join(tempfile.gettempdir(), "nope.yaml"))
        s.asr.nim.api_key = ""
        asr = NIMASR(s)
        with pytest.raises(RuntimeError, match="API key"):
            asr.transcribe(make_pcm())

    def test_pcm_to_wav_produces_valid_wav(self):
        from voiceflow.asr.nim import NIMASR
        pcm = make_pcm(500)
        wav = NIMASR._pcm_to_wav(pcm, 16000)
        buf = io.BytesIO(wav)
        with wave.open(buf) as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000

    def test_successful_transcription(self):
        from voiceflow.asr.nim import NIMASR
        s = self._make_settings()
        asr = NIMASR(s)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"text": "test transcription"}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(asr._session, "post", return_value=mock_resp):
            result = asr.transcribe(make_pcm())
        assert result == "test transcription"

    def test_http_error_raises_runtime_error(self):
        import requests
        from voiceflow.asr.nim import NIMASR
        s = self._make_settings()
        asr = NIMASR(s)

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        http_err = requests.HTTPError(response=mock_resp)
        mock_resp.raise_for_status.side_effect = http_err

        with patch.object(asr._session, "post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="HTTP error"):
                asr.transcribe(make_pcm())


# ---------------------------------------------------------------------------
# Voice commands  (via core._apply_voice_commands)
# ---------------------------------------------------------------------------

class TestVoiceCommands:
    def _make_core(self):
        from voiceflow.config.settings import Settings
        from voiceflow.core import VoiceFlowCore
        import tempfile, os
        s = Settings(os.path.join(tempfile.gettempdir(), "nope.yaml"))
        orb = MagicMock()
        # Patch heavy components so we don't need audio/model
        with patch("voiceflow.core.AudioCapture"), \
             patch("voiceflow.core.ASRManager"), \
             patch("voiceflow.core.HotkeyManager"), \
             patch("voiceflow.core.TextTyper"), \
             patch("voiceflow.core.LLMPolish"):
            core = VoiceFlowCore(s, orb)
        return core

    def test_new_line_command(self):
        core = self._make_core()
        assert core._apply_voice_commands("new line") == "\n"

    def test_period_command(self):
        core = self._make_core()
        assert core._apply_voice_commands("period") == "."

    def test_cancel_returns_none(self):
        core = self._make_core()
        assert core._apply_voice_commands("cancel") is None

    def test_delete_that_calls_undo(self):
        core = self._make_core()
        core.typer = MagicMock()
        result = core._apply_voice_commands("delete that")
        assert result is None
        core.typer.undo.assert_called_once()

    def test_normal_text_passes_through(self):
        core = self._make_core()
        text = "Hello, this is a dictation test."
        assert core._apply_voice_commands(text) == text

    def test_inline_period_substitution(self):
        core = self._make_core()
        result = core._apply_voice_commands("This is a sentence period")
        assert "." in result


# ---------------------------------------------------------------------------
# LLM Polish
# ---------------------------------------------------------------------------

class TestLLMPolish:
    def _make_polish(self, enabled=True, backend="ollama"):
        from voiceflow.config.settings import Settings
        from voiceflow.polish.llm import LLMPolish
        import tempfile, os
        s = Settings(os.path.join(tempfile.gettempdir(), "nope.yaml"))
        s.polish.enabled = enabled
        s.polish.backend = backend
        return LLMPolish(s)

    def test_disabled_returns_original(self):
        polish = self._make_polish(enabled=False)
        assert polish.refine("um hello world") == "um hello world"

    def test_empty_text_returns_empty(self):
        polish = self._make_polish(enabled=True)
        assert polish.refine("") == ""

    def test_ollama_success(self):
        polish = self._make_polish(backend="ollama")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "Hello world."}
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=mock_resp):
            result = polish.refine("um hello world")
        assert result == "Hello world."

    def test_backend_failure_returns_original(self):
        polish = self._make_polish(backend="ollama")
        with patch("requests.post", side_effect=ConnectionError("refused")):
            result = polish.refine("raw text")
        assert result == "raw text"

    def test_openrouter_missing_key_falls_back(self):
        polish = self._make_polish(backend="openrouter")
        polish.cfg.openrouter.api_key = ""
        result = polish.refine("some text")
        assert result == "some text"


# ---------------------------------------------------------------------------
# Text Injector
# ---------------------------------------------------------------------------

class TestTextTyper:
    def _make_typer(self, method="clipboard"):
        from voiceflow.config.settings import Settings
        from voiceflow.inject.typer import TextTyper
        import tempfile, os
        s = Settings(os.path.join(tempfile.gettempdir(), "nope.yaml"))
        s.injection.method = method
        s.injection.restore_clipboard = False
        return TextTyper(s)

    def test_clipboard_method_calls_pyperclip(self):
        typer = self._make_typer("clipboard")
        with patch("pyperclip.copy") as mock_copy, \
             patch("pyperclip.paste", return_value=""), \
             patch.object(typer, "_send_paste"):
            typer.type_text("hello world")
            mock_copy.assert_called_with("hello world")

    def test_keyboard_method_fallback(self):
        typer = self._make_typer("type")
        with patch("keyboard.write") as mock_write:
            typer.type_text("typed text")
            mock_write.assert_called_once()

    def test_unknown_method_uses_clipboard(self):
        typer = self._make_typer("clipboard")
        typer.cfg.method = "unknown"
        with patch.object(typer, "_inject_via_clipboard") as mock_clip:
            typer.type_text("test")
            mock_clip.assert_called_once_with("test")


# ---------------------------------------------------------------------------
# Orb state machine
# ---------------------------------------------------------------------------

class TestOrbWindow:
    def test_state_commands_enqueued(self):
        from voiceflow.config.settings import Settings
        from voiceflow.ui.orb import OrbWindow
        import tempfile, os
        s = Settings(os.path.join(tempfile.gettempdir(), "nope.yaml"))
        orb = OrbWindow(s)
        orb.set_state("listening")
        orb.show_toast("✓ 5 words", duration=1.0)
        assert orb._cmd_queue.qsize() == 2

    def test_process_state_command(self):
        from voiceflow.config.settings import Settings
        from voiceflow.ui.orb import OrbWindow
        import tempfile, os
        s = Settings(os.path.join(tempfile.gettempdir(), "nope.yaml"))
        orb = OrbWindow(s)
        orb.set_state("processing")
        orb._process_commands()
        assert orb._state == "processing"

    def test_process_toast_command(self):
        from voiceflow.config.settings import Settings
        from voiceflow.ui.orb import OrbWindow
        import tempfile, os
        s = Settings(os.path.join(tempfile.gettempdir(), "nope.yaml"))
        orb = OrbWindow(s)
        orb.show_toast("hello", duration=5.0)
        orb._process_commands()
        assert orb._toast_text == "hello"
        assert orb._toast_until > time.time()
