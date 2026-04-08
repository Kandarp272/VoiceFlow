"""
TextTyper — injects transcribed text into the currently focused application.

Strategy (in priority order):
  1. Clipboard paste (Ctrl+V / Cmd+V) — works in every text field everywhere
  2. Direct key typing via 'keyboard' library — fallback for apps without paste

The clipboard method is used by default because it:
  - Works in browsers, IDEs, Word, Outlook, Slack, Discord, Notion, etc.
  - Handles Unicode and special characters perfectly
  - Is fast (no per-character delays)

Platform support:
  - Windows: WASAPI + win32api SendInput
  - Linux: xdotool / xclip
  - macOS: pbcopy / osascript
"""

from __future__ import annotations

import logging
import platform
import subprocess
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from voiceflow.config.settings import Settings

log = logging.getLogger(__name__)

_PLATFORM = platform.system()  # "Windows", "Linux", "Darwin"


class TextTyper:
    """Injects text into the active window using the configured method."""

    def __init__(self, settings: "Settings") -> None:
        self.cfg = settings.injection
        self._last_text: str = ""
        self._clipboard_backup: str = ""

        # Verify dependencies on startup
        self._check_deps()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def type_text(self, text: str) -> None:
        """Inject text at the current cursor position in any active app."""
        self._last_text = text
        method = self.cfg.method

        if method == "clipboard":
            self._inject_via_clipboard(text)
        elif method == "type":
            self._inject_via_keyboard(text)
        else:
            log.warning("Unknown injection method %r — using clipboard", method)
            self._inject_via_clipboard(text)

    def undo(self) -> None:
        """Undo the last injected text (Ctrl+Z)."""
        try:
            import keyboard as kb  # type: ignore
            kb.send("ctrl+z")
        except Exception as exc:
            log.warning("Undo failed: %s", exc)

    # ------------------------------------------------------------------
    # Clipboard injection (primary method)
    # ------------------------------------------------------------------

    def _inject_via_clipboard(self, text: str) -> None:
        try:
            import pyperclip  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "pyperclip not installed. Run: pip install pyperclip"
            ) from exc

        # Back up current clipboard
        old_clipboard = ""
        if self.cfg.restore_clipboard:
            try:
                old_clipboard = pyperclip.paste()
            except Exception:
                pass

        try:
            pyperclip.copy(text)
            time.sleep(0.02)  # brief settle time
            self._send_paste()
            time.sleep(self.cfg.paste_delay)
        finally:
            # Restore clipboard
            if self.cfg.restore_clipboard and old_clipboard is not None:
                # Small delay so paste completes before restore
                time.sleep(0.08)
                try:
                    pyperclip.copy(old_clipboard)
                except Exception:
                    pass

        log.debug("Injected %d chars via clipboard", len(text))

    def _send_paste(self) -> None:
        """Send platform-appropriate paste shortcut."""
        try:
            import keyboard as kb  # type: ignore

            if _PLATFORM == "Darwin":
                kb.send("command+v")
            else:
                kb.send("ctrl+v")
            return
        except ImportError:
            pass

        # Fallback: platform-native paste
        if _PLATFORM == "Windows":
            self._windows_paste()
        elif _PLATFORM == "Darwin":
            self._macos_paste()
        else:
            self._linux_paste()

    def _windows_paste(self) -> None:
        try:
            import ctypes

            VK_CONTROL = 0x11
            VK_V = 0x56
            KEYEVENTF_KEYUP = 0x0002

            ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_V, 0, 0, 0)
            time.sleep(0.05)
            ctypes.windll.user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
            ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        except Exception as exc:
            log.error("Windows paste failed: %s", exc)

    def _macos_paste(self) -> None:
        subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to keystroke "v" using {command down}'],
            check=False,
        )

    def _linux_paste(self) -> None:
        subprocess.run(["xdotool", "key", "ctrl+v"], check=False)

    # ------------------------------------------------------------------
    # Keyboard typing (fallback)
    # ------------------------------------------------------------------

    def _inject_via_keyboard(self, text: str) -> None:
        try:
            import keyboard as kb  # type: ignore

            kb.write(text, delay=0.005)
            log.debug("Injected %d chars via keyboard.write", len(text))
        except ImportError as exc:
            raise RuntimeError(
                "keyboard library not installed. Run: pip install keyboard"
            ) from exc
        except Exception as exc:
            log.warning("keyboard.write failed (%s) — retrying via clipboard", exc)
            self._inject_via_clipboard(text)

    # ------------------------------------------------------------------
    # Dependency checks
    # ------------------------------------------------------------------

    def _check_deps(self) -> None:
        missing = []
        try:
            import pyperclip  # noqa: F401
        except ImportError:
            missing.append("pyperclip")
        try:
            import keyboard  # noqa: F401
        except ImportError:
            missing.append("keyboard")

        if missing:
            log.warning(
                "Optional deps missing (some injection methods may not work): %s. "
                "Install with: pip install %s",
                missing,
                " ".join(missing),
            )
