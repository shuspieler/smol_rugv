"""
UGVRover — 适配 LeRobot Robot 接口的 UGV Rover 小车驱动

接口设计遵循 LeRobot 的 Robot 基类约定：
  - get_observation() -> dict[str, Any]
  - send_action(action) -> dict[str, Any]
  - connect() / disconnect()

不继承 LeRobot Robot 基类（避免 draccus 依赖），但接口完全兼容，
可直接传入我们自己的 record.py 中使用。

串口协议参考：
  发送：{"T": "13", "X": vx, "Z": wz}
  接收：{"T": 1001, "L":..,"R":..,"ax":..,"ay":..,"az":..,"gx":..,"gy":..,"gz":..,"odl":..,"odr":..,"v":..}

速度反馈计算（与 ugv_bringup.py 保持一致）：
  vx  = ds / dt，其中 ds = ((odr - last_odr) + (odl - last_odl)) / 2.0 / 100.0  [m]
  wz  = π * gz / (16.4 * 180)  [rad/s]，gz 为 MPU 原始陀螺仪值
"""
from __future__ import annotations

import json
import logging
import math
import queue
import threading
import time
from typing import Any

import cv2
import numpy as np

from .ugv_rover_config import UGVRoverConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DummySerial — dry_run 模式下替代真实串口
# ---------------------------------------------------------------------------
class _DummySerial:
    def write(self, data: bytes) -> None:
        pass

    def readline(self) -> bytes:
        # 返回一个合法的伪 T:1001 包，模拟底盘反馈
        fake = {
            "T": 1001,
            "L": 0, "R": 0,
            "ax": 0, "ay": 0, "az": 8192,
            "gx": 0, "gy": 0, "gz": 0,
            "odl": 0, "odr": 0,
            "v": 1200,
        }
        time.sleep(0.001)
        return (json.dumps(fake) + "\n").encode()

    def reset_input_buffer(self) -> None:
        pass

    @property
    def in_waiting(self) -> int:
        return 0

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# UGVRover
# ---------------------------------------------------------------------------
class UGVRover:
    """
    UGV Rover 小车的 LeRobot 兼容驱动。

    观测空间（observation_features）：
        "x.vel"                          : float  — 底盘当前线速度 (m/s)
        "w.vel"                          : float  — 底盘当前角速度 (rad/s)
        config.camera_obs_key            : (H,W,3) — RGB 图像

    动作空间（action_features）：
        "x.vel"  : float  — 目标线速度 (m/s)
        "w.vel"  : float  — 目标角速度 (rad/s)
    """

    name = "ugv_rover"

    def __init__(self, config: UGVRoverConfig):
        self.config = config
        self._connected = False

        # 串口对象（connect 时初始化）
        self._ser = None
        self._serial_thread: threading.Thread | None = None
        self._serial_stop = threading.Event()

        # 最新底盘反馈数据（线程安全）
        self._feedback_lock = threading.Lock()
        self._latest_feedback: dict = {
            "T": 1001,
            "L": 0, "R": 0,
            "ax": 0, "ay": 0, "az": 0,
            "gx": 0, "gy": 0, "gz": 0,
            "odl": 0, "odr": 0,
            "v": 0,
        }

        # 里程计增量状态（用于计算 vx）
        self._last_odl: float = 0.0
        self._last_odr: float = 0.0
        self._last_odom_time: float = 0.0

        # 最新计算好的速度（供 get_observation 使用）
        self._vx: float = 0.0
        self._wz: float = 0.0

        # 摄像头对象（connect 时初始化）
        self._cap: cv2.VideoCapture | None = None

        # 命令发送队列（异步写串口，避免阻塞 control loop）
        self._cmd_queue: queue.Queue = queue.Queue(maxsize=10)
        self._cmd_thread: threading.Thread | None = None
        self._cmd_stop_sentinel = object()

    # ------------------------------------------------------------------
    # 接口属性
    # ------------------------------------------------------------------

    @property
    def observation_features(self) -> dict:
        """观测空间描述，供 LeRobotDataset 建立 schema 使用"""
        h = self.config.camera.height
        w = self.config.camera.width
        return {
            "x.vel": float,
            "w.vel": float,
            self.config.camera_obs_key: (h, w, 3),
        }

    @property
    def action_features(self) -> dict:
        """动作空间描述"""
        return {
            "x.vel": float,
            "w.vel": float,
        }

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_calibrated(self) -> bool:
        # 差速底盘无需标定
        return True

    # ------------------------------------------------------------------
    # connect / disconnect
    # ------------------------------------------------------------------

    def connect(self, calibrate: bool = False) -> None:
        """
        建立串口连接并打开摄像头。
        calibrate 参数保留以兼容 LeRobot 接口，对本小车无意义。
        """
        if self._connected:
            logger.warning("UGVRover already connected.")
            return

        logger.info(f"Connecting UGVRover (dry_run={self.config.dry_run})...")

        # --- 串口 ---
        if self.config.dry_run:
            self._ser = _DummySerial()
            logger.info("DRY RUN: using dummy serial.")
        else:
            import serial
            self._ser = serial.Serial(
                self.config.serial.port,
                self.config.serial.baud,
                timeout=self.config.serial.timeout,
            )
            logger.info(f"Serial opened: {self.config.serial.port} @ {self.config.serial.baud}")

        # 初始化里程计基准
        self._last_odl = 0.0
        self._last_odr = 0.0
        self._last_odom_time = time.perf_counter()

        # 启动串口读取后台线程
        self._serial_stop.clear()
        self._serial_thread = threading.Thread(
            target=self._serial_reader_loop, daemon=True, name="ugv-serial-reader"
        )
        self._serial_thread.start()

        # 启动命令发送后台线程
        self._cmd_thread = threading.Thread(
            target=self._cmd_sender_loop, daemon=True, name="ugv-cmd-sender"
        )
        self._cmd_thread.start()

        # --- 摄像头 ---
        if self.config.dry_run:
            self._cap = None
            logger.info("DRY RUN: skipping camera.")
        else:
            self._cap = cv2.VideoCapture(self.config.camera.index)
            if not self._cap.isOpened():
                raise RuntimeError(
                    f"Cannot open camera at index {self.config.camera.index}. "
                    "Check if the device is connected."
                )
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.camera.width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.camera.height)
            self._cap.set(cv2.CAP_PROP_FPS, self.config.camera.fps)
            # 暖机读取几帧，避免第一帧黑屏
            for _ in range(5):
                self._cap.read()
            logger.info(
                f"Camera opened: index={self.config.camera.index} "
                f"{self.config.camera.width}x{self.config.camera.height}@{self.config.camera.fps}"
            )

        self._connected = True
        logger.info("UGVRover connected.")

    def calibrate(self) -> None:
        """差速底盘无需标定，空操作"""
        pass

    def configure(self) -> None:
        """无需额外配置"""
        pass

    def disconnect(self) -> None:
        """断开连接前先刹停小车"""
        if not self._connected:
            return

        logger.info("Disconnecting UGVRover — sending stop command...")
        # 发送零速度确保小车停止
        self._send_serial({"T": 13, "X": 0.0, "Z": 0.0})
        time.sleep(0.1)

        # 停止后台线程
        self._serial_stop.set()
        if self._serial_thread:
            self._serial_thread.join(timeout=2.0)
        # 清空命令队列并停止发送线程
        self._enqueue_stop_sentinel()
        if self._cmd_thread:
            self._cmd_thread.join(timeout=2.0)

        # 关闭串口
        if self._ser:
            self._ser.close()
            self._ser = None

        # 释放摄像头
        if self._cap:
            self._cap.release()
            self._cap = None

        self._connected = False
        logger.info("UGVRover disconnected.")

    # ------------------------------------------------------------------
    # get_observation
    # ------------------------------------------------------------------

    def get_observation(self) -> dict[str, Any]:
        """
        返回当前观测：
          - 从最新串口反馈计算线速度 vx 和角速度 wz
          - 从摄像头读取一帧 RGB 图像
        """
        if not self._connected:
            raise RuntimeError("UGVRover is not connected. Call connect() first.")

        # 1. 读取最新速度（在串口线程中持续更新）
        vx = self._vx
        wz = self._wz

        # 2. 读取摄像头图像
        if self.config.dry_run or self._cap is None:
            image = np.zeros(
                (self.config.camera.height, self.config.camera.width, 3), dtype=np.uint8
            )
        else:
            ret, frame = self._cap.read()
            if not ret:
                logger.warning("Camera read failed, using blank frame.")
                image = np.zeros(
                    (self.config.camera.height, self.config.camera.width, 3), dtype=np.uint8
                )
            else:
                # BGR → RGB（LeRobot/SmolVLA 期望 RGB）
                image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        return {
            "x.vel": float(vx),
            "w.vel": float(wz),
            self.config.camera_obs_key: image,
        }

    # ------------------------------------------------------------------
    # send_action
    # ------------------------------------------------------------------

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """
        将动作转换为串口 JSON 并发送给 ESP32。

        Args:
            action: {"x.vel": float, "w.vel": float}

        Returns:
            实际发送的动作（与输入相同，无裁剪）
        """
        if not self._connected:
            raise RuntimeError("UGVRover is not connected.")

        vx = float(action.get("x.vel", 0.0))
        wz = float(action.get("w.vel", 0.0))

        payload = {"T": 13, "X": round(vx, 4), "Z": round(wz, 4)}
        self._enqueue_cmd(payload)

        return {"x.vel": vx, "w.vel": wz}

    # ------------------------------------------------------------------
    # 内部：串口读取后台线程
    # ------------------------------------------------------------------

    def _serial_reader_loop(self) -> None:
        """
        持续读取串口，解析 T:1001 反馈包，计算并更新 _vx / _wz。
        在 connect() 启动，直到 _serial_stop 被触发。
        """
        while not self._serial_stop.is_set():
            try:
                chunk = self._ser.readline()
                if not chunk:
                    continue

                # 尝试解析 JSON
                try:
                    line = chunk.decode("utf-8").strip()
                    if not line:
                        continue
                    data = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue

                if data.get("T") != 1001:
                    continue

                # 更新最新反馈 & 计算速度
                with self._feedback_lock:
                    self._latest_feedback = data
                    self._update_velocity(data)

            except Exception as exc:
                if not self._serial_stop.is_set():
                    logger.debug(f"Serial reader error: {exc}")
                time.sleep(0.001)

    def _update_velocity(self, data: dict) -> None:
        """
        根据里程计增量和陀螺仪计算 vx、wz。
        注意：此方法在 _feedback_lock 持有期间调用，可直接读写内部状态。
        """
        now = time.perf_counter()

        # --- 线速度：里程计增量 / dt ---
        # odl/odr 单位为 cm，转换为 m
        odl_m = float(data.get("odl", 0)) / 100.0
        odr_m = float(data.get("odr", 0)) / 100.0

        dt = now - self._last_odom_time
        if dt > 1e-6 and self._last_odom_time > 0:
            dl = odl_m - self._last_odl
            dr = odr_m - self._last_odr
            ds = (dl + dr) / 2.0
            vx_raw = ds / dt
            # 噪声剔除：里程计跳变 >= 5 m/s 为 ESP32 重启/溢出异常帧，丢弃
            if abs(vx_raw) < 5.0:
                self._vx = vx_raw
            else:
                logger.debug(f"odometry spike ignored: vx_raw={vx_raw:.2f} dl={dl:.4f} dr={dr:.4f} dt={dt:.4f}")
        else:
            self._vx = 0.0

        self._last_odl = odl_m
        self._last_odr = odr_m
        self._last_odom_time = now

        # --- 角速度：陀螺仪 gz（MPU6050：16.4 LSB/°/s，与 ugv_bringup.py 公式一致）---
        gz_raw = float(data.get("gz", 0))
        wz_raw = math.pi * gz_raw / (16.4 * 180.0)
        # 噪声剔除：陀螺仪超过 20 rad/s 为异常数据
        self._wz = wz_raw if abs(wz_raw) < 20.0 else 0.0

    # ------------------------------------------------------------------
    # 内部：命令发送后台线程
    # ------------------------------------------------------------------

    def _cmd_sender_loop(self) -> None:
        """消费 _cmd_queue 并写入串口，确保串口写操作串行化"""
        while True:
            payload = self._cmd_queue.get()
            if payload is self._cmd_stop_sentinel:  # 退出哨兵
                break
            try:
                data = json.dumps(payload) + "\n"
                self._ser.write(data.encode("utf-8"))
            except Exception as exc:
                logger.warning(f"Serial write error: {exc}")

    def _enqueue_stop_sentinel(self) -> None:
        """非阻塞放入退出哨兵，避免 disconnect 在队列满时卡住。"""
        while True:
            try:
                self._cmd_queue.put_nowait(self._cmd_stop_sentinel)
                return
            except queue.Full:
                try:
                    self._cmd_queue.get_nowait()
                except queue.Empty:
                    # 理论上不会发生；让出调度后重试
                    time.sleep(0.001)

    def _enqueue_cmd(self, payload: dict) -> None:
        """非阻塞地将命令放入发送队列（队列满时丢弃最旧命令）"""
        try:
            self._cmd_queue.put_nowait(payload)
        except queue.Full:
            try:
                self._cmd_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._cmd_queue.put_nowait(payload)
            except queue.Full:
                pass

    def _send_serial(self, payload: dict) -> None:
        """同步写串口（仅 disconnect 时使用）"""
        if self._ser:
            try:
                self._ser.write((json.dumps(payload) + "\n").encode("utf-8"))
            except Exception as exc:
                logger.warning(f"_send_serial error: {exc}")
