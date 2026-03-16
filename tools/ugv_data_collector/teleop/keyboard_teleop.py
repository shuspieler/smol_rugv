"""
KeyboardUGVTeleop — 键盘遥控器

将 WASD 键盘输入映射为 UGV 差速底盘的动作命令 {"x.vel": float, "w.vel": float}。

设计说明：
- 使用 pynput 监听键盘，不阻塞主循环
- 任意时刻调用 get_action() 即可获取当前键盘状态对应的速度命令
- 速度按档位缩放（Q/E 调速），范围由 max_linear / max_angular 限制
- 按 Space 急停（零速度），按 Enter 结束当前 Episode（通过 event 回调通知）
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
DEFAULT_SPEED_SCALES = [0.1, 0.2, 0.3, 0.5, 0.7, 1.0]
DEFAULT_SCALE_IDX = 1   # 默认第 2 档（0.2）


class KeyboardUGVTeleop:
    """
    键盘遥控器，输出 UGV 动作命令。

    Args:
        max_linear:      最大线速度（m/s）
        max_angular:     最大角速度（rad/s）
        speed_scales:    速度档位列表，实际速度 = max * scale
        default_scale_idx: 默认档位索引
        on_episode_end:  Enter 键回调，用于通知 record.py 结束当前 Episode
        on_quit:         Esc / Ctrl+C 回调，用于通知退出
    """

    def __init__(
        self,
        max_linear: float = 0.5,
        max_angular: float = 1.5,
        speed_scales: list[float] | None = None,
        default_scale_idx: int = DEFAULT_SCALE_IDX,
        on_episode_end: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
    ):
        self.max_linear = max_linear
        self.max_angular = max_angular
        self.speed_scales = speed_scales or DEFAULT_SPEED_SCALES
        self._scale_idx = min(default_scale_idx, len(self.speed_scales) - 1)
        self.on_episode_end = on_episode_end
        self.on_quit = on_quit

        # 当前按键状态（pynput 在另一个线程中更新）
        self._lock = threading.Lock()
        self._keys_pressed: set[str] = set()
        self._e_stop: bool = False   # Space 急停标志（按下 Space 后一直为 True，直到下一次非急停按键）

        self._listener = None
        self._connected = False

    # ------------------------------------------------------------------
    # connect / disconnect
    # ------------------------------------------------------------------

    def connect(self) -> None:
        try:
            from pynput import keyboard as _kb
            self._kb_module = _kb
        except ImportError:
            raise ImportError(
                "pynput is required for keyboard teleoperation. "
                "Install it with: pip install pynput"
            )

        self._listener = self._kb_module.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()
        self._connected = True
        logger.info(
            "Keyboard teleop connected. "
            f"Controls: W/S=forward/back, A/D=left/right, "
            f"Q/E=speed up/down, Space=stop, Enter=end episode, Esc=quit."
        )

    def disconnect(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
        self._connected = False
        logger.info("Keyboard teleop disconnected.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # get_action
    # ------------------------------------------------------------------

    def get_action(self) -> dict[str, Any]:
        """
        根据当前按键状态返回速度命令。
        调用频率由外部控制循环决定（例如 30Hz）。

        Returns:
            {"x.vel": float, "w.vel": float}
        """
        with self._lock:
            pressed = set(self._keys_pressed)
            e_stop = self._e_stop

        if e_stop:
            return {"x.vel": 0.0, "w.vel": 0.0}

        scale = self.speed_scales[self._scale_idx]
        lin = self.max_linear * scale
        ang = self.max_angular * scale

        vx = 0.0
        wz = 0.0

        if "w" in pressed:
            vx += lin
        if "s" in pressed:
            vx -= lin
        if "a" in pressed:
            wz += ang
        if "d" in pressed:
            wz -= ang

        return {"x.vel": round(vx, 4), "w.vel": round(wz, 4)}

    # ------------------------------------------------------------------
    # 当前速度档信息（供 UI 显示）
    # ------------------------------------------------------------------

    @property
    def current_scale(self) -> float:
        return self.speed_scales[self._scale_idx]

    @property
    def current_scale_idx(self) -> int:
        return self._scale_idx

    # ------------------------------------------------------------------
    # pynput 回调
    # ------------------------------------------------------------------

    def _on_press(self, key) -> None:
        key_char = self._key_to_char(key)
        if key_char is None:
            return

        with self._lock:
            if key_char == "space":
                # 急停：清空方向键，锁定零速度
                self._e_stop = True
                self._keys_pressed.clear()
                logger.info("E-STOP activated (Space pressed)")
                return

            # 任何方向键解除急停
            if key_char in ("w", "s", "a", "d"):
                self._e_stop = False

            if key_char in ("w", "s", "a", "d"):
                self._keys_pressed.add(key_char)

        # 速度档调节（在锁外执行，避免死锁）
        if key_char == "q":
            self._scale_idx = min(self._scale_idx + 1, len(self.speed_scales) - 1)
            logger.info(f"Speed scale UP: {self.current_scale:.1f} (idx={self._scale_idx})")
        elif key_char == "e":
            self._scale_idx = max(self._scale_idx - 1, 0)
            logger.info(f"Speed scale DOWN: {self.current_scale:.1f} (idx={self._scale_idx})")
        elif key_char == "enter":
            logger.info("Enter pressed — episode end signal")
            if self.on_episode_end:
                self.on_episode_end()
        elif key_char == "esc":
            logger.info("Esc pressed — quit signal")
            if self.on_quit:
                self.on_quit()

    def _on_release(self, key) -> None:
        key_char = self._key_to_char(key)
        if key_char in ("w", "s", "a", "d"):
            with self._lock:
                self._keys_pressed.discard(key_char)

    @staticmethod
    def _key_to_char(key) -> str | None:
        """将 pynput Key 对象转换为简单字符串标识"""
        try:
            # 普通字符键
            return key.char.lower() if key.char else None
        except AttributeError:
            pass
        # 特殊键
        try:
            from pynput.keyboard import Key
            mapping = {
                Key.space: "space",
                Key.enter: "enter",
                Key.esc: "esc",
            }
            return mapping.get(key)
        except Exception:
            return None
