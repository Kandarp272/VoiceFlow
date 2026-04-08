"""
VADFilter — wraps webrtcvad for frame-level voice activity detection.
Falls back to energy-based VAD if webrtcvad is unavailable.
"""

from __future__ import annotations

import logging
import struct

log = logging.getLogger(__name__)

# Supported sample rates for webrtcvad
_VAD_SAMPLE_RATES = {8000, 16000, 32000, 48000}


class VADFilter:
    """
    Voice Activity Detector.

    Uses webrtcvad (Google's WebRTC VAD) when available,
    falls back to simple RMS energy threshold otherwise.
    """

    # Energy threshold for fallback mode (0–1 float32 audio)
    _ENERGY_THRESHOLD = 0.01

    def __init__(self, aggressiveness: int = 2, sample_rate: int = 16000) -> None:
        if sample_rate not in _VAD_SAMPLE_RATES:
            raise ValueError(
                f"webrtcvad only supports sample rates: {_VAD_SAMPLE_RATES}"
            )
        self._sample_rate = sample_rate
        self._aggressiveness = aggressiveness
        self._vad = None
        self._use_webrtcvad = False

        try:
            import webrtcvad  # type: ignore

            self._vad = webrtcvad.Vad(aggressiveness)
            self._use_webrtcvad = True
            log.debug("webrtcvad loaded (aggressiveness=%d)", aggressiveness)
        except ImportError:
            log.warning(
                "webrtcvad not installed — falling back to energy-based VAD. "
                "Install with: pip install webrtcvad-wheels"
            )

    def is_speech(self, pcm_bytes: bytes) -> bool:
        """
        Return True if pcm_bytes contains speech.
        pcm_bytes must be 16-bit signed PCM at the configured sample rate.
        Length must be 10, 20, or 30 ms worth of frames.
        """
        if self._use_webrtcvad:
            try:
                return self._vad.is_speech(pcm_bytes, self._sample_rate)  # type: ignore
            except Exception as exc:
                log.debug("webrtcvad error: %s — using energy fallback", exc)

        return self._energy_vad(pcm_bytes)

    def _energy_vad(self, pcm_bytes: bytes) -> bool:
        """Simple RMS energy threshold — always available."""
        n = len(pcm_bytes) // 2
        if n == 0:
            return False
        samples = struct.unpack(f"<{n}h", pcm_bytes)
        rms = (sum(s * s for s in samples) / n) ** 0.5
        # 32768 is max int16 value; normalise to 0-1
        return (rms / 32768.0) > self._ENERGY_THRESHOLD
