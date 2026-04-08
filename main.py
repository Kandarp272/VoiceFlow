#!/usr/bin/env python3
"""
VoiceFlow — Offline-first AI voice dictation for any app.
Entry point: starts the orb UI on the main thread and spawns all background services.
"""

import sys
import signal
import logging
import threading
import argparse

from voiceflow.config.settings import Settings
from voiceflow.core import VoiceFlowCore
from voiceflow.ui.orb import OrbWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("voiceflow")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="VoiceFlow — AI voice dictation for any app"
    )
    p.add_argument("--config", default="config.yaml", help="Path to config file")
    p.add_argument(
        "--backend",
        choices=["local", "nim", "auto"],
        help="Override ASR backend from config",
    )
    p.add_argument(
        "--model",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Override local Whisper model size",
    )
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load configuration
    settings = Settings(args.config)
    if args.backend:
        settings.asr.backend = args.backend
    if args.model:
        settings.asr.local.model = args.model

    log.info("Starting VoiceFlow — backend=%s", settings.asr.backend)

    # Create the orb window (must live on main thread for tkinter)
    orb = OrbWindow(settings)

    # Create core and wire it to the orb
    core = VoiceFlowCore(settings, orb)

    # Graceful shutdown on SIGINT / SIGTERM
    def _shutdown(signum, frame):
        log.info("Shutting down…")
        core.stop()
        orb.quit()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Start all background threads inside core
    core_thread = threading.Thread(target=core.start, daemon=True, name="core")
    core_thread.start()

    # Run tkinter main loop (blocks until orb.quit() is called)
    try:
        orb.run()
    except KeyboardInterrupt:
        _shutdown(None, None)

    log.info("VoiceFlow stopped.")
    sys.exit(0)


if __name__ == "__main__":
    main()
