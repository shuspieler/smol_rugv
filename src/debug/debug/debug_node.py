#!/usr/bin/env python3
"""
debug_node.py — 底盘调试节点

功能：
  1. 键盘遥控底盘（WASD）+ 急停（空格），直接发布 /cmd_vel 和 /e_stop，
     完全绕过 VLA 推理链路。
  2. 订阅 /camera/image_raw，将画面叠加 OSD（速度/档位/e-stop 状态）后
     通过内置 MJPEG HTTP 服务推流到浏览器，适用于无头/SSH 场景。

话题：
  订阅 /camera/image_raw  (sensor_msgs/Image)
  发布 /cmd_vel            (geometry_msgs/Twist)
  发布 /e_stop             (std_msgs/Bool)

ROS2 参数：
  keyboard_device  str,   "auto"  — /dev/input/event* 路径；auto 时自动扫描
  linear_speed     float, 0.3     — 基础线速度 (m/s)
  angular_speed    float, 0.8     — 基础角速度 (rad/s)
  speed_step       float, 0.05    — Q/E 每次调节步长
  speed_min        float, 0.05    — 最小速度倍率
  speed_max        float, 1.0     — 最大速度倍率
  publish_hz       float, 20.0    — cmd_vel 发布频率 (Hz)
  stream_port      int,   8080    — MJPEG HTTP 端口
  stream_quality   int,   75      — JPEG 编码质量 (1-100)
"""
from __future__ import annotations

import os
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSDurabilityPolicy, QoSHistoryPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, Float32

# ---------------------------------------------------------------------------
# Linux input_event 布局
# ---------------------------------------------------------------------------
_EVENT_FMT  = "llHHi"
_EVENT_SIZE = struct.calcsize(_EVENT_FMT)

EV_KEY      = 0x01
KEY_PRESS   = 1
KEY_HOLD    = 2
KEY_RELEASE = 0

_KEY_W     = 17
_KEY_A     = 30
_KEY_S     = 31
_KEY_D     = 32
_KEY_Q     = 16
_KEY_E     = 18
_KEY_SPACE = 57
_KEY_ESC   = 1


# ---------------------------------------------------------------------------
# evdev 工具
# ---------------------------------------------------------------------------

def _find_keyboard_device() -> Optional[str]:
    """自动扫描第一个支持 KEY_W 的 /dev/input/event* 设备。"""
    input_dir = "/sys/class/input"
    if not os.path.isdir(input_dir):
        return None
    for entry in sorted(os.listdir(input_dir)):
        if not entry.startswith("event"):
            continue
        cap_path = os.path.join(input_dir, entry, "device", "capabilities", "key")
        try:
            with open(cap_path) as f:
                caps = f.read().strip()
            bits = int(caps.replace(" ", ""), 16)
            if bits & (1 << _KEY_W):
                return f"/dev/input/{entry}"
        except (OSError, ValueError):
            continue
    return None


# ---------------------------------------------------------------------------
# evdev 读取线程
# ---------------------------------------------------------------------------

class _EvdevReader(threading.Thread):
    def __init__(self, device_path: str, logger) -> None:
        super().__init__(daemon=True, name="evdev_reader")
        self._device_path = device_path
        self._logger = logger
        self._lock = threading.Lock()
        self._held_keys: set[int] = set()
        self._running = True
        self._fd: Optional[int] = None

    def run(self) -> None:
        try:
            self._fd = os.open(self._device_path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            self._logger.error(f"[debug] 无法打开设备 {self._device_path}: {exc}")
            return
        self._logger.info(f"[debug] 键盘设备已连接: {self._device_path}")
        while self._running:
            try:
                raw = os.read(self._fd, _EVENT_SIZE)
            except BlockingIOError:
                time.sleep(0.002)
                continue
            except OSError as exc:
                self._logger.error(f"[debug] 设备读取错误: {exc}")
                break
            if len(raw) < _EVENT_SIZE:
                continue
            _, _, ev_type, ev_code, ev_value = struct.unpack(_EVENT_FMT, raw)
            if ev_type != EV_KEY:
                continue
            with self._lock:
                if ev_value in (KEY_PRESS, KEY_HOLD):
                    self._held_keys.add(ev_code)
                elif ev_value == KEY_RELEASE:
                    self._held_keys.discard(ev_code)

    def get_held(self) -> set[int]:
        with self._lock:
            return set(self._held_keys)

    def stop(self) -> None:
        self._running = False
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# MJPEG 流服务器
# ---------------------------------------------------------------------------

_HTML_PAGE = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>smol_rugv Debug View</title>
  <style>
    body {{ background:#111; color:#eee; font-family:monospace;
            display:flex; flex-direction:column; align-items:center; padding:16px; }}
    h2   {{ margin:8px 0; }}
    img  {{ border:2px solid #444; max-width:100%; }}
    .hint{{ margin-top:12px; font-size:13px; color:#aaa; line-height:1.8; }}
  </style>
</head>
<body>
  <h2>smol_rugv — Debug Camera Stream</h2>
  <img src="/stream" alt="camera stream">
  <div class="hint">
    WASD — 移动 &nbsp;|&nbsp; 空格 — 急停/解除 &nbsp;|&nbsp;
    Q/E — 降速/加速 &nbsp;|&nbsp; Esc — 退出节点
  </div>
</body>
</html>
"""


class _MjpegServer:
    """纯 stdlib MJPEG HTTP 服务，后台单线程运行。"""

    def __init__(self, port: int, logger) -> None:
        self._port = port
        self._logger = logger
        self._lock = threading.Lock()
        self._latest_jpg: bytes = b""
        self._started = False

    def update_frame(self, jpg_bytes: bytes) -> None:
        with self._lock:
            self._latest_jpg = jpg_bytes

    def start(self) -> None:
        if self._started:
            return
        self._started = True

        server = self          # 闭包引用

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass  # 静默 access log

            def do_GET(self):
                if self.path == "/":
                    body = _HTML_PAGE.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/stream":
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        "multipart/x-mixed-replace; boundary=frame",
                    )
                    self.end_headers()
                    try:
                        while True:
                            with server._lock:
                                jpg = server._latest_jpg
                            if jpg:
                                self.wfile.write(
                                    b"--frame\r\n"
                                    b"Content-Type: image/jpeg\r\n\r\n"
                                    + jpg
                                    + b"\r\n"
                                )
                            time.sleep(0.033)   # ~30 fps 上限
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                else:
                    self.send_response(404)
                    self.end_headers()

        srv = HTTPServer(("0.0.0.0", self._port), _Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True, name="mjpeg-server")
        t.start()

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            lan_ip = s.getsockname()[0]
            s.close()
        except Exception:
            lan_ip = "<robot-ip>"

        self._logger.info(
            f"[debug] 摄像头预览已启动，在同局域网浏览器打开：\n"
            f"        http://{lan_ip}:{self._port}/"
        )


# ---------------------------------------------------------------------------
# OSD 叠加
# ---------------------------------------------------------------------------

def _draw_osd(
    frame_bgr: np.ndarray,
    e_stop: bool,
    scale: float,
    vx_cmd: float,
    wz_cmd: float,
    vx_fb: float,
    wz_fb: float,
    voltage: float,
) -> np.ndarray:
    """在左上角叠加状态信息，返回修改后的画面（in-place）。"""
    lines = [
        f"E-STOP: {'!! ON !!' if e_stop else 'off'}",
        f"scale : {scale:.2f}",
        f"vx cmd: {vx_cmd:+.2f}  fb: {vx_fb:+.2f} m/s",
        f"wz cmd: {wz_cmd:+.2f}  fb: {wz_fb:+.2f} r/s",
        f"volts : {voltage:.2f} V" if voltage > 0.0 else "volts : --",
    ]
    stop_color  = (0, 0, 220)
    norm_color  = (0, 220, 80)
    y0 = 28
    for i, line in enumerate(lines):
        y = y0 + i * 26
        color = stop_color if (e_stop and i == 0) else norm_color
        cv2.putText(frame_bgr, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 3)
        cv2.putText(frame_bgr, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
    return frame_bgr


# ---------------------------------------------------------------------------
# ROS2 节点
# ---------------------------------------------------------------------------

class DebugNode(Node):
    def __init__(self) -> None:
        super().__init__("debug_node")

        # --- 参数 ---
        self.declare_parameter("keyboard_device", "auto")
        self.declare_parameter("linear_speed",   0.3)
        self.declare_parameter("angular_speed",  0.8)
        self.declare_parameter("speed_step",     0.05)
        self.declare_parameter("speed_min",      0.05)
        self.declare_parameter("speed_max",      1.0)
        self.declare_parameter("publish_hz",     20.0)
        self.declare_parameter("stream_port",    8080)
        self.declare_parameter("stream_quality", 75)

        device_param    = self.get_parameter("keyboard_device").value
        self._lin_base  = self.get_parameter("linear_speed").value
        self._ang_base  = self.get_parameter("angular_speed").value
        self._step      = self.get_parameter("speed_step").value
        self._spd_min   = self.get_parameter("speed_min").value
        self._spd_max   = self.get_parameter("speed_max").value
        pub_hz          = self.get_parameter("publish_hz").value
        stream_port     = self.get_parameter("stream_port").value
        self._jpg_qual  = self.get_parameter("stream_quality").value

        # --- 状态 ---
        self._scale          = 1.0
        self._e_stop_active  = False
        self._prev_space     = False
        self._prev_q         = False
        self._prev_e         = False
        self._last_vx        = 0.0   # 指令速度
        self._last_wz        = 0.0
        self._fb_vx          = 0.0   # odom 反馈速度
        self._fb_wz          = 0.0
        self._voltage        = 0.0   # 电压反馈

        # --- 话题 ---
        self._cmd_pub  = self.create_publisher(Twist, "cmd_vel", 10)
        self._stop_pub = self.create_publisher(Bool,  "e_stop",  10)

        sensor_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            durability=QoSDurabilityPolicy.VOLATILE,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self._bridge = CvBridge()
        self._img_sub = self.create_subscription(
            Image,
            "/camera/image_raw",
            self._image_callback,
            sensor_qos,
        )
        self._odom_sub = self.create_subscription(
            Odometry,
            "/odom/odom_raw",
            self._odom_callback,
            sensor_qos,
        )
        self._voltage_sub = self.create_subscription(
            Float32,
            "/voltage",
            self._voltage_callback,
            sensor_qos,
        )

        # --- MJPEG 服务 ---
        self._mjpeg = _MjpegServer(stream_port, self.get_logger())
        self._mjpeg.start()

        # --- evdev（键盘可选：无键盘时仅提供 MJPEG 推流）---
        device_path = device_param if device_param != "auto" else _find_keyboard_device()
        if device_path is None:
            self.get_logger().warn(
                "[debug] 未找到键盘设备，键盘控制不可用，但摄像头推流正常运行。\n"
                "  如需键盘控制，请通过参数 keyboard_device:=/dev/input/eventN 手动指定设备"
            )
            self._reader: Optional[_EvdevReader] = None
        else:
            self._reader = _EvdevReader(device_path, self.get_logger())
            self._reader.start()

        # --- 控制定时器 ---
        self._timer = self.create_timer(1.0 / pub_hz, self._control_loop)

        self.get_logger().info(
            f"[debug] 节点启动  device={device_path}  stream_port={stream_port}\n"
            + ("  WASD 移动 | 空格 急停/解除 | Q/E 减速/加速 | Esc 退出"
               if device_path else "  摄像头推流模式（无键盘控制）")
        )

    # ------------------------------------------------------------------
    def _odom_callback(self, msg: Odometry) -> None:
        """从 /odom/odom_raw 获取底盘实际速度反馈，用于 OSD 显示。"""
        self._fb_vx = msg.twist.twist.linear.x
        self._fb_wz = msg.twist.twist.angular.z

    def _voltage_callback(self, msg: Float32) -> None:
        """从 /voltage 获取电池电压，用于 OSD 显示。"""
        self._voltage = msg.data

    # ------------------------------------------------------------------
    def _image_callback(self, msg: Image) -> None:
        """订阅图像，叠加 OSD后推入 MJPEG 流。"""
        try:
            frame_bgr = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().warn(f"[debug] cv_bridge 转换失败: {exc}")
            return

        _draw_osd(frame_bgr, self._e_stop_active, self._scale,
                  self._last_vx, self._last_wz,
                  self._fb_vx, self._fb_wz,
                  self._voltage)

        ret, buf = cv2.imencode(
            ".jpg", frame_bgr,
            [cv2.IMWRITE_JPEG_QUALITY, self._jpg_qual],
        )
        if ret:
            self._mjpeg.update_frame(buf.tobytes())

    # ------------------------------------------------------------------
    def _control_loop(self) -> None:
        if self._reader is None:
            return
        held = self._reader.get_held()

        # Esc → 退出
        if _KEY_ESC in held:
            self.get_logger().info("[debug] Esc 收到，节点退出")
            self._reader.stop()
            rclpy.shutdown()
            return

        # 空格急停（边沿触发）
        space_now = _KEY_SPACE in held
        if space_now and not self._prev_space:
            self._e_stop_active = True
            msg = Bool(); msg.data = True
            self._stop_pub.publish(msg)
            self.get_logger().warn("[debug] !! 急停触发 !!")
        elif not space_now and self._prev_space and self._e_stop_active:
            self._e_stop_active = False
            msg = Bool(); msg.data = False
            self._stop_pub.publish(msg)
            self.get_logger().info("[debug] 急停解除")
        self._prev_space = space_now

        # Q/E 速度档（上升沿）
        q_now = _KEY_Q in held
        e_now = _KEY_E in held
        if q_now and not self._prev_q:
            self._scale = max(self._spd_min, round(self._scale - self._step, 3))
            self.get_logger().info(f"[debug] 速度档 ↓  scale={self._scale:.2f}")
        if e_now and not self._prev_e:
            self._scale = min(self._spd_max, round(self._scale + self._step, 3))
            self.get_logger().info(f"[debug] 速度档 ↑  scale={self._scale:.2f}")
        self._prev_q = q_now
        self._prev_e = e_now

        # 构造并发布 Twist
        twist = Twist()
        if not self._e_stop_active:
            if _KEY_W in held:
                twist.linear.x  += self._lin_base * self._scale
            if _KEY_S in held:
                twist.linear.x  -= self._lin_base * self._scale
            if _KEY_A in held:
                twist.angular.z += self._ang_base * self._scale
            if _KEY_D in held:
                twist.angular.z -= self._ang_base * self._scale

        self._last_vx = twist.linear.x
        self._last_wz = twist.angular.z
        self._cmd_pub.publish(twist)

    # ------------------------------------------------------------------
    def destroy_node(self) -> None:
        if self._reader is not None:
            self._reader.stop()
        super().destroy_node()


# ---------------------------------------------------------------------------

def main(args=None) -> None:
    rclpy.init(args=args)
    try:
        node = DebugNode()
        rclpy.spin(node)
    except RuntimeError:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
