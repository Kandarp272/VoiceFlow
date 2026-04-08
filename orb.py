"""
OrbWindow — a small, always-on-top floating orb that shows dictation state.

States and visuals:
  idle        — hidden (minimised to a tiny grey ghost)
  listening   — pulsing red orb with glow
  processing  — spinning blue arc animation
  done        — green flash, then back to idle
  error       — orange flash, then idle

Uses tkinter for cross-platform compatibility (no extra GUI deps).
PIL (Pillow) is used to render smooth, anti-aliased glow effects.
Falls back to simpler canvas drawing if PIL is unavailable.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from voiceflow.config.settings import Settings

log = logging.getLogger(__name__)

# State → (primary_color_hex, glow_color_hex, label)
STATE_STYLES: dict[str, tuple[str, str, str]] = {
    "idle":       ("#1e293b", "#0f172a", ""),
    "listening":  ("#ef4444", "#dc2626", "● REC"),
    "processing": ("#38bdf8", "#0ea5e9", "⟳ ..."),
    "done":       ("#22c55e", "#16a34a", "✓"),
    "error":      ("#f97316", "#ea580c", "⚠"),
}


class OrbWindow:
    """
    Floating orb UI. Must be created and run on the main thread.
    Other threads communicate via thread-safe queue calls.
    """

    _PULSE_PERIOD = 900    # ms for one full pulse cycle
    _SPIN_STEP    = 8      # degrees per frame for spinner
    _FPS          = 40     # target animation frame rate
    _FRAME_MS     = 1000 // _FPS

    def __init__(self, settings: "Settings") -> None:
        self.cfg = settings.ui.orb
        self._state = "idle"
        self._cmd_queue: queue.Queue = queue.Queue()

        # Animation state
        self._pulse_t = 0.0
        self._spin_angle = 0.0
        self._toast_text = ""
        self._toast_until = 0.0

        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._pil_available = self._check_pil()

        # Try to import PIL early
        if self._pil_available:
            from PIL import Image, ImageDraw, ImageFilter, ImageTk  # noqa: F401

    # ------------------------------------------------------------------
    # Thread-safe public API (callable from any thread)
    # ------------------------------------------------------------------

    def set_state(self, state: str) -> None:
        """Thread-safe: update orb state."""
        self._cmd_queue.put(("state", state))

    def show_toast(self, message: str, duration: float = 2.5) -> None:
        """Thread-safe: show a brief toast message."""
        self._cmd_queue.put(("toast", message, duration))

    def quit(self) -> None:
        """Thread-safe: destroy the window and exit the mainloop."""
        if self._root:
            self._root.after(0, self._root.quit)

    # ------------------------------------------------------------------
    # Main thread API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Create window and enter Tkinter mainloop. Blocks until quit()."""
        self._root = tk.Tk()
        self._setup_window()
        self._setup_canvas()
        self._position_window()
        self._schedule_frame()
        self._root.mainloop()

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        root = self._root
        size = self.cfg.size + 20  # extra padding for glow

        root.overrideredirect(True)        # no title bar / borders
        root.wm_attributes("-topmost", True)
        root.wm_attributes("-alpha", self.cfg.opacity)
        root.configure(bg="black")

        # Windows: make black transparent (true shape cut-out)
        try:
            root.wm_attributes("-transparentcolor", "black")
        except Exception:
            pass

        root.resizable(False, False)

        # Allow dragging the orb
        root.bind("<ButtonPress-1>",   self._on_drag_start)
        root.bind("<B1-Motion>",       self._on_drag_motion)
        root.bind("<ButtonRelease-1>", self._on_drag_end)

        self._drag_x = 0
        self._drag_y = 0
        self._total_w = size
        self._total_h = size

    def _setup_canvas(self) -> None:
        size = self._total_w
        self._canvas = tk.Canvas(
            self._root,
            width=size,
            height=size,
            bg="black",
            highlightthickness=0,
        )
        self._canvas.pack()
        self._canvas_size = size

    def _position_window(self) -> None:
        root = self._root
        root.update_idletasks()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        m = self.cfg.margin
        s = self._total_w
        pos = self.cfg.position

        if pos == "bottom-right":
            x, y = sw - s - m, sh - s - m - 40   # 40px taskbar offset
        elif pos == "bottom-left":
            x, y = m, sh - s - m - 40
        elif pos == "top-right":
            x, y = sw - s - m, m
        else:  # top-left
            x, y = m, m

        root.geometry(f"{s}x{s}+{x}+{y}")

    # ------------------------------------------------------------------
    # Animation loop
    # ------------------------------------------------------------------

    def _schedule_frame(self) -> None:
        if self._root:
            self._root.after(self._FRAME_MS, self._frame)

    def _frame(self) -> None:
        self._process_commands()
        self._draw()
        self._schedule_frame()

    def _process_commands(self) -> None:
        while not self._cmd_queue.empty():
            try:
                cmd = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            if cmd[0] == "state":
                self._state = cmd[1]
                log.debug("Orb state → %s", cmd[1])
            elif cmd[0] == "toast":
                self._toast_text = cmd[1]
                self._toast_until = time.time() + cmd[2]

    def _draw(self) -> None:
        if not self._canvas:
            return

        self._canvas.delete("all")
        state = self._state
        style = STATE_STYLES.get(state, STATE_STYLES["idle"])
        color, glow_color, label = style

        cs = self._canvas_size
        cx = cy = cs // 2
        r = self.cfg.size // 2 - 4

        if state == "idle":
            self._draw_idle_orb(cx, cy, r)
        elif state == "listening":
            self._draw_listening_orb(cx, cy, r, color, glow_color)
        elif state == "processing":
            self._draw_processing_orb(cx, cy, r, color)
        elif state == "done":
            self._draw_flash_orb(cx, cy, r, color)
        elif state == "error":
            self._draw_flash_orb(cx, cy, r, color)

        # Label text
        if label:
            self._canvas.create_text(
                cx, cy,
                text=label,
                fill="white",
                font=("Helvetica", 9, "bold"),
            )

        # Toast overlay
        if self._toast_text and time.time() < self._toast_until:
            self._draw_toast()

    def _draw_idle_orb(self, cx: int, cy: int, r: int) -> None:
        """Very small, dim circle — barely visible."""
        self._canvas.create_oval(
            cx - 6, cy - 6, cx + 6, cy + 6,
            fill="#1e293b", outline="#334155", width=1
        )

    def _draw_listening_orb(
        self, cx: int, cy: int, r: int, color: str, glow: str
    ) -> None:
        """Pulsing orb with animated rings."""
        # Advance pulse timer
        self._pulse_t += self._FRAME_MS / self._PULSE_PERIOD
        pulse = (math.sin(self._pulse_t * 2 * math.pi) + 1) / 2  # 0..1

        # Outer glow ring (fades in and out)
        glow_r = int(r + 8 + pulse * 10)
        alpha_hex = format(int(40 + pulse * 60), "02x")
        self._canvas.create_oval(
            cx - glow_r, cy - glow_r, cx + glow_r, cy + glow_r,
            outline=glow + "99", fill="", width=2,
        )

        # Mid ring
        mid_r = r + 4
        self._canvas.create_oval(
            cx - mid_r, cy - mid_r, cx + mid_r, cy + mid_r,
            outline=color + "66", fill="", width=1,
        )

        # Main circle — scales slightly with pulse
        main_r = int(r - 2 + pulse * 3)
        self._canvas.create_oval(
            cx - main_r, cy - main_r, cx + main_r, cy + main_r,
            fill=color, outline="",
        )

        # Inner bright spot
        self._canvas.create_oval(
            cx - 8, cy - 14, cx + 8, cy - 4,
            fill="#ffffff33", outline="",
        )

    def _draw_processing_orb(self, cx: int, cy: int, r: int, color: str) -> None:
        """Spinning arc on a dim circle."""
        # Advance spinner
        self._spin_angle = (self._spin_angle + self._SPIN_STEP) % 360

        # Background circle
        self._canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            fill="#0f172a", outline=color + "44", width=2,
        )

        # Spinning arc (drawn as a series of dots for tkinter compat)
        for i in range(0, 180, 15):
            angle_rad = math.radians(self._spin_angle + i)
            fade = 1.0 - i / 180
            dot_r = int(3 + fade * 3)
            dx = int(r * 0.75 * math.cos(angle_rad))
            dy = int(r * 0.75 * math.sin(angle_rad))
            intensity = int(fade * 255)
            dot_color = "#{:02x}{:02x}{:02x}".format(
                min(255, int(intensity * 0.22)),
                min(255, int(intensity * 0.74)),
                min(255, intensity),
            )
            self._canvas.create_oval(
                cx + dx - dot_r, cy + dy - dot_r,
                cx + dx + dot_r, cy + dy + dot_r,
                fill=dot_color, outline="",
            )

        # Centre dot
        self._canvas.create_oval(
            cx - 4, cy - 4, cx + 4, cy + 4,
            fill=color, outline="",
        )

    def _draw_flash_orb(self, cx: int, cy: int, r: int, color: str) -> None:
        """Solid bright circle for done/error flash."""
        self._canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            fill=color, outline="",
        )
        self._canvas.create_oval(
            cx - 10, cy - r + 6, cx + 10, cy - r + 18,
            fill="#ffffff44", outline="",
        )

    def _draw_toast(self) -> None:
        """Draw a small pill-shaped toast message above/below the orb."""
        cs = self._canvas_size
        text = self._toast_text
        tx = cs // 2
        ty = cs // 2 - cs // 2 - 14  # above orb

        # Shadow / bg pill
        self._canvas.create_rectangle(
            tx - 60, ty - 10, tx + 60, ty + 10,
            fill="#0f172a", outline="#1e293b", width=1,
        )
        self._canvas.create_text(
            tx, ty,
            text=text,
            fill="#e2e8f0",
            font=("Helvetica", 9),
        )

    # ------------------------------------------------------------------
    # Drag support
    # ------------------------------------------------------------------

    def _on_drag_start(self, event) -> None:
        self._drag_x = event.x_root - self._root.winfo_x()
        self._drag_y = event.y_root - self._root.winfo_y()

    def _on_drag_motion(self, event) -> None:
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self._root.geometry(f"+{x}+{y}")

    def _on_drag_end(self, event) -> None:
        pass

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _check_pil() -> bool:
        try:
            import PIL  # noqa: F401
            return True
        except ImportError:
            return False
