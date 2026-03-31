"""Evdev keyboard teleop backend aligned with ugv_ctrl_tester behavior."""
from __future__ import annotations

import glob
import logging
import select
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_SPEED_SCALES = [0.3, 0.6, 1.0]
DEFAULT_SCALE_IDX = 1


class EvdevUGVTeleop:
    """Evdev-based keyboard teleop with ctrl_test-compatible control state machine."""

    # Linux input key codes
    _KEY_MAP = {
        1:  "esc",     # KEY_ESC
        16: "q",       # KEY_Q
        17: "w",       # KEY_W
        18: "e",       # KEY_E
        28: "enter",   # KEY_ENTER
        30: "a",       # KEY_A
        31: "s",       # KEY_S
        32: "d",       # KEY_D
        57: "space",   # KEY_SPACE
    }

    def __init__(
        self,
        max_linear: float = 0.5,
        max_angular: float = 1.5,
        speed_scales: list[float] | None = None,
        default_scale_idx: int = DEFAULT_SCALE_IDX,
        on_quit: Callable[[], None] | None = None,
        on_enter: Callable[[], None] | None = None,
        device_path: str | None = None,
    ):
        self._max_linear = max_linear
        self._max_angular = max_angular
        self.speed_scales = speed_scales or DEFAULT_SPEED_SCALES
        self._scale_idx = default_scale_idx
        self.on_quit = on_quit or (lambda: None)
        self.on_enter = on_enter or (lambda: None)
        self._device_path = device_path
        self._on_key_event = lambda key, direction: None

        self._lock = threading.Lock()
        self._held: set[str] = set()
        self._vx = 0.0
        self._wz = 0.0
        self._estop_active = False

        self._device = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_estop_active(self) -> bool:
        with self._lock:
            return self._estop_active

    @property
    def current_scale(self) -> float:
        with self._lock:
            return self.speed_scales[self._scale_idx]

    @property
    def current_scale_idx(self) -> int:
        with self._lock:
            return self._scale_idx

    def connect(self) -> None:
        try:
            import evdev
        except ImportError as exc:
            raise ImportError(
                "evdev is required for evdev backend. Install with: pip install evdev"
            ) from exc

        self._device = self._find_keyboard(evdev, self._device_path)
        if self._device is None:
            raise RuntimeError(
                "No keyboard input device found. Check keyboard connection and /dev/input permissions."
            )

        self._stop.clear()
        self._thread = threading.Thread(target=self._reader_loop, daemon=True, name="evdev-keyboard")
        self._thread.start()
        self._connected = True
        logger.info(
            "Evdev teleop connected: %s (%s)",
            self._device.path,
            self._device.name,
        )

    def disconnect(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._device:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None
        self._connected = False
        logger.info("Evdev teleop disconnected.")

    def get_action(self) -> dict[str, Any]:
        with self._lock:
            return {"x.vel": self._vx, "w.vel": self._wz}

    @classmethod
    def _find_keyboard(cls, evdev_mod, preferred: str | None):
        if preferred:
            return evdev_mod.InputDevice(preferred)

        for path in sorted(glob.glob("/dev/input/event*")):
            try:
                dev = evdev_mod.InputDevice(path)
                keys = dev.capabilities().get(evdev_mod.ecodes.EV_KEY, [])
                # Heuristic: W + Space available -> likely keyboard
                if 17 in keys and 57 in keys:
                    return dev
                dev.close()
            except Exception:
                continue
        return None

    def _reader_loop(self) -> None:
        import evdev

        fd = self._device.fileno()
        while not self._stop.is_set():
            r, _, _ = select.select([fd], [], [], 0.05)
            if not r:
                continue
            try:
                for event in self._device.read():
                    if event.type != evdev.ecodes.EV_KEY:
                        continue
                    name = self._KEY_MAP.get(event.code)
                    if name is None:
                        continue
                    if event.value == 1:
                        self._on_press(name)
                    elif event.value == 0:
                        self._on_release(name)
            except Exception:
                break

    def _on_press(self, key: str) -> None:
        with self._lock:
            if key == "esc":
                self._stop.set()
                self.on_quit()
                self._on_key_event(key, "down")
                return

            if key == "enter":
                self.on_enter()  # 调用不带锁，回调函数自己负责线程安全
                self._on_key_event(key, "down")
                return

            if key == "space":
                self._held.clear()
                self._vx = 0.0
                self._wz = 0.0
                self._estop_active = True
                self._on_key_event("space", "down")
                return

            if key == "q":
                self._scale_idx = min(self._scale_idx + 1, len(self.speed_scales) - 1)
                self._update_vel_locked()
                self._on_key_event(key, "down")
                return
            if key == "e":
                self._scale_idx = max(self._scale_idx - 1, 0)
                self._update_vel_locked()
                self._on_key_event(key, "down")
                return

            self._estop_active = False  # 操作员重新按键，解除急停
            self._held.add(key)
            self._update_vel_locked()
            self._on_key_event(key, "down")

    def _on_release(self, key: str) -> None:
        if key in ("w", "s", "a", "d"):
            with self._lock:
                self._held.discard(key)
                self._update_vel_locked()
                self._on_key_event(key, "up")

    def _update_vel_locked(self) -> None:
        """Update current velocity vector from held keys. Caller must hold lock."""
        scale = self.speed_scales[self._scale_idx]
        vx = self._max_linear * scale
        wz = self._max_angular * scale
        self._vx = (("w" in self._held) - ("s" in self._held)) * vx
        self._wz = (("a" in self._held) - ("d" in self._held)) * wz
