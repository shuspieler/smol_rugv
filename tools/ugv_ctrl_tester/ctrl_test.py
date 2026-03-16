#!/usr/bin/env python3
"""
ctrl_test.py — UGV 控制通路快速验证工具

功能：
  - 键盘（WASD）实时控制 UGV Rover 运动
  - 不依赖 LeRobot，无数据集逻辑
  - 简易抽样记录，用于验证控制通路和查看实际效果：
      * 图片：每 IMAGE_INTERVAL 秒保存一张 JPEG
      * 控制/反馈日志：每 LOG_INTERVAL 秒追加一行到 CSV

输出目录：
  output/<YYYYMMDD_HHMMSS>/
      images/   ← frame_<seq>_<timestamp>.jpg
      ctrl_log.csv

键盘操作：
  W / S       前进 / 后退
  A / D       左转 / 右转
  Q / E       速度档升 / 降
  Space       急停
  Esc / Ctrl+C  退出

用法：
    python ctrl_test.py
    python ctrl_test.py --dry_run
    python ctrl_test.py --serial_port /dev/ttyCH341USB0 --camera_index 0
    python ctrl_test.py --image_interval 5 --log_interval 1
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径：复用 ugv_data_collector 中的 robots / teleop 模块，不重复实现
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_COLLECTOR_DIR = os.path.abspath(os.path.join(_SCRIPT_DIR, "../ugv_data_collector"))

if _COLLECTOR_DIR not in sys.path:
    sys.path.insert(0, _COLLECTOR_DIR)

# ---------------------------------------------------------------------------
# 默认值
# ---------------------------------------------------------------------------
DEFAULT_SERIAL_PORT    = "/dev/ttyCH341USB0"
DEFAULT_CAMERA_INDEX   = 0
DEFAULT_CONTROL_HZ     = 10       # 控制循环频率（Hz）
DEFAULT_IMAGE_INTERVAL = 5.0      # 图片采样间隔（秒）
DEFAULT_LOG_INTERVAL   = 1.0      # CSV 日志采样间隔（秒）
DEFAULT_OUTPUT_ROOT    = os.path.join(_SCRIPT_DIR, "output")

CSV_HEADER = [
    "timestamp",          # ISO 时间字符串
    "elapsed_s",          # 距会话开始的秒数
    "keys_held",          # 当前按住的按键（空格分隔，如 "w a"）
    "vx_cmd",             # 指令线速度（m/s）
    "wz_cmd",             # 指令角速度（rad/s）
    "vx_actual",          # 底盘反馈线速度（m/s）
    "wz_actual",          # 底盘反馈角速度（rad/s）
    "odl",                # 左轮里程计原始值
    "odr",                # 右轮里程计原始值
    "voltage_V",          # 电池电压（V；来自底盘反馈 v/100）
    "speed_scale",        # 当前速度档
    "image_saved",        # 本行是否同时保存了图片（0/1）
]

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ctrl_test")


# ---------------------------------------------------------------------------
# 输出目录初始化
# ---------------------------------------------------------------------------

def _init_output_dir(root: str) -> tuple[Path, Path, Path]:
    """
    创建本次会话的输出目录，返回 (session_dir, images_dir, csv_path)。
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = Path(root) / ts
    images_dir  = session_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    csv_path = session_dir / "ctrl_log.csv"
    return session_dir, images_dir, csv_path


# ---------------------------------------------------------------------------
# EvdevKeyboard — 直读 /dev/input/event*，无需 X11 / 终端
# 适用：SSH、VS Code 终端、USB 键盘直插 Jetson 完全无头场景
# ---------------------------------------------------------------------------

class EvdevKeyboard:
    """
    通过 evdev 直接从内核输入层读取键盘事件，彻底绕开 X11 和终端限制。

    接口与 KeyboardUGVTeleop 兼容：
        .connect() / .disconnect()
        .get_action()  ->  {"x.vel": float, "w.vel": float}
        .current_scale / .current_scale_idx / .speed_scales
    """

    # Linux 标准 input key code（无需 import evdev 即可硬编码）
    _KEY_MAP = {
        1:  "esc",    # KEY_ESC
        16: "q",      # KEY_Q（降速）
        17: "w",      # KEY_W（前进）
        18: "e",      # KEY_E（加速）
        30: "a",      # KEY_A（左转）
        31: "s",      # KEY_S（后退）
        32: "d",      # KEY_D（右转）
        57: "space",  # KEY_SPACE（急停）
    }

    def __init__(
        self,
        max_linear: float = 0.5,
        max_angular: float = 1.5,
        speed_scales=None,
        default_scale_idx: int = 1,
        on_episode_end=None,   # 保留兼容参数，不使用
        on_quit=None,
        on_key_event=None,     # callback(key, "down"|"up") 每次按键时调用
        device_path: str | None = None,
    ):
        self._max_linear  = max_linear
        self._max_angular = max_angular
        self.speed_scales = speed_scales or [0.3, 0.6, 1.0]
        self._scale_idx   = default_scale_idx
        self._on_quit      = on_quit or (lambda: None)
        self._on_key_event = on_key_event or (lambda k, d: None)
        self._device_path  = device_path  # None → 自动发现
        self._held: set    = set()
        self._vx  = 0.0
        self._wz  = 0.0
        self._lock   = threading.Lock()
        self._stop   = threading.Event()
        self._thread: threading.Thread | None = None
        self._device = None

    # ---- 属性 ----
    @property
    def current_scale(self) -> float:
        return self.speed_scales[self._scale_idx]

    @property
    def current_scale_idx(self) -> int:
        return self._scale_idx

    @property
    def keys_held(self) -> str:
        """当前按住的按键，空格分隔字符串，供显示和CSV使用。"""
        with self._lock:
            return " ".join(sorted(self._held)) if self._held else ""

    # ---- 设备发现 ----
    @staticmethod
    def _find_keyboard(preferred: str | None = None):
        import glob as _glob
        import evdev as _ev
        if preferred:
            return _ev.InputDevice(preferred)
        # evdev.list_devices() 依赖 udev，在无桌面/无 input 组时可能返回空。
        # 改用 glob 直接扫描 /dev/input/event*，只要文件可读即可（crw-rw-r-- others=r）。
        paths = sorted(_glob.glob("/dev/input/event*"))
        logger.debug(f"[EvdevKeyboard] 扫描到设备: {paths}")
        for path in paths:
            try:
                dev  = _ev.InputDevice(path)
                keys = dev.capabilities().get(_ev.ecodes.EV_KEY, [])
                # KEY_W(17) + KEY_SPACE(57) 同时存在 → 是键盘
                if 17 in keys and 57 in keys:
                    return dev
                dev.close()
            except Exception as ex:
                logger.debug(f"[EvdevKeyboard] 跳过 {path}: {ex}")
                continue
        return None

    # ---- connect / disconnect ----
    def connect(self):
        self._device = self._find_keyboard(self._device_path)
        if self._device is None:
            raise RuntimeError(
                "未找到键盘设备。请确认键盘已连接，且当前用户在 input 组：\n"
                "  sudo usermod -aG input $USER    # 重新登录后生效\n"
                "  sudo chmod a+r /dev/input/event*  # 临时方案"
            )
        logger.info(f"[EvdevKeyboard] 设备: {self._device.path}  ({self._device.name})")
        self._stop.clear()
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def disconnect(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._device:
            try:
                self._device.close()
            except Exception:
                pass

    # ---- 后台读取线程 ----
    def _reader_loop(self):
        import select as _sel
        import evdev as _ev
        fd = self._device.fileno()
        while not self._stop.is_set():
            r, _, _ = _sel.select([fd], [], [], 0.05)
            if not r:
                continue
            try:
                for ev in self._device.read():
                    if ev.type != _ev.ecodes.EV_KEY:
                        continue
                    name = self._KEY_MAP.get(ev.code)
                    if name is None:
                        continue
                    if ev.value == 1:    # key_down
                        self._on_press(name)
                    elif ev.value == 0:  # key_up
                        self._on_release(name)
            except Exception:
                break

    def _on_press(self, key: str):
        with self._lock:
            if key == "esc":
                self._stop.set()
                self._on_quit()
                self._on_key_event(key, "down")
                return
            if key == "space":
                self._held.clear()
                self._vx = self._wz = 0.0
                self._on_key_event("space", "down")
                return
            if key == "q":
                self._scale_idx = min(self._scale_idx + 1, len(self.speed_scales) - 1)
                self._update_vel()
                self._on_key_event(key, "down")
                return
            if key == "e":
                self._scale_idx = max(self._scale_idx - 1, 0)
                self._update_vel()
                self._on_key_event(key, "down")
                return
            self._held.add(key)
            self._update_vel()
            self._on_key_event(key, "down")

    def _on_release(self, key: str):
        with self._lock:
            self._held.discard(key)
            self._update_vel()
            self._on_key_event(key, "up")

    def _update_vel(self):
        """根据当前按键集合计算速度向量（调用方须持 _lock）。"""
        s  = self.speed_scales[self._scale_idx]
        vx = self._max_linear  * s
        wz = self._max_angular * s
        self._vx = (('w' in self._held) - ('s' in self._held)) * vx
        self._wz = (('a' in self._held) - ('d' in self._held)) * wz

    def get_action(self) -> dict:
        with self._lock:
            return {"x.vel": self._vx, "w.vel": self._wz}


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------

def run_test(args: argparse.Namespace) -> None:
    # --- 延迟导入重量级依赖 ---
    try:
        import cv2
        from robots import UGVRover, UGVRoverConfig
    except ImportError as e:
        logger.error(f"导入失败: {e}")
        logger.error(f"请确认 ugv_data_collector 目录存在：{_COLLECTOR_DIR}")
        logger.error("并已运行 pip install -r requirements.txt")
        sys.exit(1)

    # --- 加载 Rover 配置 ---
    config_path = os.path.join(_COLLECTOR_DIR, "config", "ugv_config.yaml")
    if os.path.exists(config_path):
        config = UGVRoverConfig.from_yaml(config_path)
        logger.info(f"配置来自: {config_path}")
    else:
        config = UGVRoverConfig()
        logger.warning("未找到 ugv_config.yaml，使用默认配置")

    # 命令行参数覆盖
    if args.serial_port:
        config.serial.port = args.serial_port
    if args.camera_index is not None:
        config.camera.index = args.camera_index
    if args.dry_run:
        config.dry_run = True

    # --- 初始化输出目录 ---
    session_dir, images_dir, csv_path = _init_output_dir(args.output_dir)
    logger.info(f"会话输出目录: {session_dir}")

    # --- 初始化 Robot ---
    robot = UGVRover(config)
    robot.connect()
    logger.info("Robot 已连接")

    # --- 初始化键盘遥控 ---
    quit_event = [False]

    def _on_quit():
        quit_event[0] = True

    import yaml
    teleop_cfg = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            teleop_cfg = yaml.safe_load(f).get("teleop", {})

    # 按键事件队列：后台线程写入，主循环打印（线程安全）
    import collections
    key_event_queue: collections.deque = collections.deque(maxlen=32)

    def _on_key_event(key: str, direction: str):
        """后台键盘线程回调：把事件推入队列，主循环负责打印。"""
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        arrow = "↓" if direction == "down" else "↑"
        key_event_queue.append(f"[KEY] {ts}  {key}{arrow}")

    teleop = EvdevKeyboard(
        max_linear=teleop_cfg.get("max_linear", 0.5),
        max_angular=teleop_cfg.get("max_angular", 1.5),
        speed_scales=teleop_cfg.get("speed_scales"),
        default_scale_idx=teleop_cfg.get("default_scale_idx", 1),
        on_quit=_on_quit,
        on_key_event=_on_key_event,
        device_path=args.keyboard_device,
    )
    teleop.connect()
    logger.info("键盘遥控已启动 (W/S/A/D 移动，Space 急停，Q/E 调速，Esc 退出)")

    # --- 打开 CSV ---
    csv_file   = open(csv_path, "w", newline="", encoding="utf-8")
    csv_writer = csv.DictWriter(csv_file, fieldnames=CSV_HEADER)
    csv_writer.writeheader()
    csv_file.flush()

    period         = 1.0 / args.control_hz
    img_interval   = args.image_interval
    log_interval   = args.log_interval

    last_img_time  = 0.0   # 上次保存图片的时间
    last_log_time  = 0.0   # 上次写 CSV 的时间
    img_seq        = 0
    log_count      = 0
    session_start  = time.perf_counter()

    _print_header()

    try:
        while not quit_event[0]:
            loop_start = time.perf_counter()
            now_wall   = time.time()
            elapsed    = loop_start - session_start

            # 1. 获取遥控指令
            action = teleop.get_action()
            vx_cmd = action.get("x.vel", 0.0)
            wz_cmd = action.get("w.vel", 0.0)

            # 2. 发送给底盘
            robot.send_action(action)

            # 3. 读取观测（底盘反馈 + 图像）
            obs = robot.get_observation()
            vx_actual = obs.get("x.vel", 0.0)
            wz_actual = obs.get("w.vel", 0.0)

            # 原始反馈（含里程计、电压）
            raw = robot._latest_feedback   # type: dict
            odl     = raw.get("odl", 0)
            odr     = raw.get("odr", 0)
            voltage = raw.get("v", 0) / 100.0   # v 单位为 0.01V

            image_saved = 0

            # 4. 图片采样
            if loop_start - last_img_time >= img_interval:
                frame = obs.get(config.camera_obs_key)   # numpy (H,W,3) RGB
                if frame is not None:
                    import numpy as np
                    fname = f"frame_{img_seq:05d}_{datetime.now().strftime('%H%M%S')}.jpg"
                    fpath = images_dir / fname
                    # LeRobot 惯例：numpy 是 RGB，cv2 写文件需 BGR
                    cv2.imwrite(str(fpath), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                    img_seq      += 1
                    image_saved   = 1
                    logger.info(f"[图片] 已保存 {fpath.name}（seq={img_seq}）")
                last_img_time = loop_start

            # 5. CSV 日志采样
            if loop_start - last_log_time >= log_interval:
                row = {
                    "timestamp":   datetime.fromtimestamp(now_wall).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                    "elapsed_s":   f"{elapsed:.2f}",
                    "keys_held":   teleop.keys_held,
                    "vx_cmd":      f"{vx_cmd:.4f}",
                    "wz_cmd":      f"{wz_cmd:.4f}",
                    "vx_actual":   f"{vx_actual:.4f}",
                    "wz_actual":   f"{wz_actual:.4f}",
                    "odl":         odl,
                    "odr":         odr,
                    "voltage_V":   f"{voltage:.2f}",
                    "speed_scale": f"{teleop.current_scale:.2f}",
                    "image_saved": image_saved,
                }
                csv_writer.writerow(row)
                csv_file.flush()
                log_count += 1
                last_log_time = loop_start

            # 6. 终端状态显示（每次控制循环刷新）
            # 先把积压的按键事件滚动打印出来（换行输出，不覆盖状态行）
            while key_event_queue:
                print(f"\r{key_event_queue.popleft()}", flush=True)
            _print_status(
                elapsed=elapsed,
                vx_cmd=vx_cmd, wz_cmd=wz_cmd,
                vx_actual=vx_actual, wz_actual=wz_actual,
                voltage=voltage,
                scale=teleop.current_scale,
                scale_idx=teleop.current_scale_idx,
                n_scales=len(teleop.speed_scales),
                keys_held=teleop.keys_held,
                img_seq=img_seq,
                log_count=log_count,
            )

            # 7. 定频睡眠
            elapsed_loop = time.perf_counter() - loop_start
            sleep_time = period - elapsed_loop
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("\n收到 Ctrl+C，退出...")
    finally:
        # 保存最后一帧
        try:
            obs   = robot.get_observation()
            frame = obs.get(config.camera_obs_key)
            if frame is not None:
                import numpy as np
                fpath = images_dir / f"frame_{img_seq:05d}_final.jpg"
                cv2.imwrite(str(fpath), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                logger.info(f"[图片] 最终帧已保存: {fpath.name}")
        except Exception:
            pass

        csv_file.close()
        teleop.disconnect()
        robot.disconnect()

        total = time.perf_counter() - session_start
        print(
            f"\n{'='*50}\n"
            f"  会话结束。运行时长: {total:.1f}s\n"
            f"  图片数量: {img_seq}  日志行数: {log_count}\n"
            f"  输出目录: {session_dir}\n"
            f"{'='*50}"
        )


# ---------------------------------------------------------------------------
# 终端显示工具
# ---------------------------------------------------------------------------

def _print_header() -> None:
    print(
        "\n"
        "╔══════════════════════════════════════════════════╗\n"
        "║           UGV 控制通路验证工具  ctrl_test         ║\n"
        "║  W/S=前后  A/D=左右  Q/E=调速  Space=急停  Esc=退出 ║\n"
        "╚══════════════════════════════════════════════════╝\n"
    )


def _print_status(
    elapsed: float,
    vx_cmd: float, wz_cmd: float,
    vx_actual: float, wz_actual: float,
    voltage: float,
    scale: float,
    scale_idx: int,
    n_scales: int,
    keys_held: str,
    img_seq: int,
    log_count: int,
) -> None:
    """用 \r 原地刷新单行状态，不滚动终端。"""
    keys_display = f"[{keys_held}]" if keys_held else "[--]"
    line = (
        f"\r t={elapsed:6.1f}s | "
        f"keys={keys_display:<6} | "
        f"cmd v={vx_cmd:+.2f} w={wz_cmd:+.2f} | "
        f"act v={vx_actual:+.2f} w={wz_actual:+.2f} | "
        f"batt={voltage:.2f}V | "
        f"scale={scale:.2f}({scale_idx+1}/{n_scales}) | "
        f"img={img_seq} log={log_count}"
    )
    print(line, end="", flush=True)


# ---------------------------------------------------------------------------
# 串口诊断模式
# ---------------------------------------------------------------------------

def run_serial_diag(args: argparse.Namespace) -> None:
    """
    直接读取串口，逐行打印解析到的底盘反馈包，并发送一次测试指令。
    用于验证：收包是否正常 / 组包是否正常 / 发送是否正常。
    """
    import json as _json
    import math as _math
    import serial as _serial

    port = args.serial_port or DEFAULT_SERIAL_PORT
    baud = 115200
    diag_secs = getattr(args, "diag_seconds", 10.0)

    print(f"""
╔{'='*62}╗
║  串口诊断模式  port={port}  baud={baud}  时长={diag_secs}s
║  验证项目: 收包完整性 / T:1001字段 / 计算vx wz / 发送T:13
╚{'='*62}╝
""")

    try:
        ser = _serial.Serial(port, baud, timeout=1.0)
    except Exception as e:
        print(f"[ERROR] 无法打开串口 {port}: {e}")
        print("  提示: 当前项目默认使用 CH341 USB 转串口，一般为 /dev/ttyCH341USB0")
        return

    class _RL:
        def __init__(self, s):
            self.buf = bytearray()
            self.s = s
        def readline(self):
            """带超时的行读取：最多等待 2s，超时返回空 bytes。"""
            import time as _t
            deadline = _t.perf_counter() + 2.0
            i = self.buf.find(b"\n")
            if i >= 0:
                r = self.buf[:i+1]; self.buf = self.buf[i+1:]; return r
            while _t.perf_counter() < deadline:
                waiting = self.s.in_waiting
                if waiting == 0:
                    _t.sleep(0.005)
                    continue
                i = max(1, min(512, waiting))
                data = self.s.read(i)
                if not data:
                    continue
                i = data.find(b"\n")
                if i >= 0:
                    r = self.buf + data[:i+1]; self.buf[0:] = data[i+1:]; return r
                else:
                    self.buf.extend(data)
            # 超时：返回已积累的内容（即使没有 \n）
            r = bytes(self.buf); self.buf = bytearray(); return r
        def clear(self):
            self.s.reset_input_buffer(); self.buf = bytearray()

    rl = _RL(ser)

    # 发送测试指令（T 必须是整数 13，不是字符串 "13"）
    test_cmd = {"T": 13, "X": 0.0, "Z": 0.0}
    raw_cmd  = _json.dumps(test_cmd) + "\n"
    ser.write(raw_cmd.encode("utf-8"))
    print(f"[发送] >>> {raw_cmd.strip()}")
    print(f"       注: T 为整数 13，不是字符串 \"13\"（历史 bug 已修复）")
    print()

    total    = 0
    good     = 0
    bad      = 0
    bad_shown = 0   # 最多打印前 5 条 BAD 详情，避免刷屏
    last_odl = None
    last_odr = None
    last_t_p = None
    t_start  = time.perf_counter()

    print(f"{'#':>4}  {'odl':>8}  {'odr':>8}  {'gz':>7}  {'v(V)':>6}  {'vx(m/s)':>10}  {'wz(r/s)':>10}  状态")
    print("-" * 80)

    try:
        while time.perf_counter() - t_start < diag_secs:
            total += 1
            try:
                chunk = rl.readline()
                line  = chunk.decode("utf-8").strip()
                data  = _json.loads(line)
            except (UnicodeDecodeError, _json.JSONDecodeError) as e:
                bad += 1
                if bad_shown < 5:
                    bad_shown += 1
                    raw_preview = chunk[:40].hex() if chunk else "(empty)"
                    printable = chunk[:40].replace(b'\x00', b'.').replace(b'\n', b'N').replace(b'\r', b'R')
                    try:
                        printable_str = printable.decode("utf-8", errors="replace")
                    except Exception:
                        printable_str = repr(printable)
                    print(f"{total:>4}  [BAD] {str(e)[:30]}  hex={raw_preview}  txt={printable_str!r}")
                elif bad_shown == 5:
                    bad_shown += 1
                    print(f"      [BAD 后续不再打印详情，继续统计...]")
                rl.clear()
                continue

            if data.get("T") != 1001:
                bad += 1
                print(f"{total:>4}  [SKIP] 非T:1001包: T={data.get('T')}")
                continue

            good   += 1
            odl     = float(data.get("odl", 0))
            odr     = float(data.get("odr", 0))
            gz      = float(data.get("gz", 0))
            v       = float(data.get("v",   0)) / 100.0
            now_p   = time.perf_counter()

            if last_odl is None:
                vx_str = "    --init--"
            else:
                dt = now_p - last_t_p
                dl = (odl - last_odl) / 100.0
                dr = (odr - last_odr) / 100.0
                ds = (dl + dr) / 2.0
                vx_raw = ds / dt if dt > 1e-6 else 0.0
                flag   = "!SPIKE" if abs(vx_raw) >= 5.0 else ""
                vx_str = f"{vx_raw:>+10.4f}{flag}"

            wz_raw   = _math.pi * gz / (16.4 * 180.0)
            wz_flag  = "!SPIKE" if abs(wz_raw) >= 20.0 else ""
            print(
                f"{good:>4}  "
                f"{odl:>8.0f}  "
                f"{odr:>8.0f}  "
                f"{gz:>7.0f}  "
                f"{v:>6.2f}  "
                f"{vx_str:<16}  "
                f"{wz_raw:>+10.4f}{wz_flag}"
            )
            last_odl = odl; last_odr = odr; last_t_p = now_p

    except KeyboardInterrupt:
        pass
    finally:
        ser.write((_json.dumps({"T": 13, "X": 0.0, "Z": 0.0}) + "\n").encode())
        ser.close()

    elapsed = time.perf_counter() - t_start
    rate    = good / elapsed if elapsed > 0 else 0.0
    print()
    print(f"诊断结束: 运行 {elapsed:.1f}s | 总行={total} T:1001={good} 异常={bad} | 有效包率={rate:.1f} Hz")
    if bad > total * 0.1:
        print("  [警告] 异常包占比 > 10%，请检查串口接线/波特率/串口号")
    if good == 0:
        print("  [错误] 未收到任何 T:1001 反馈包！")
        print("  可能原因:")
        print("    1. 串口号错误: 当前方案应使用 /dev/ttyCH341USB0")
        print("    2. CH341 驱动未加载或设备节点未出现")
        print("    3. 对方尚未起来或波特率不匹配")


# ---------------------------------------------------------------------------
# 命令行参数
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="UGV 控制通路快速验证工具（无 LeRobot 依赖）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--serial_port",    default=None,
                        help=f"串口路径，默认读 ugv_config.yaml（通常 {DEFAULT_SERIAL_PORT}）")
    parser.add_argument("--camera_index",   type=int, default=None,
                        help="摄像头序号 /dev/videoN")
    parser.add_argument("--dry_run",        action="store_true",
                        help="不连接真实硬件，用虚拟底盘和摄像头运行")
    parser.add_argument("--control_hz",     type=float, default=DEFAULT_CONTROL_HZ,
                        help="控制循环频率（Hz）")
    parser.add_argument("--image_interval", type=float, default=DEFAULT_IMAGE_INTERVAL,
                        help="图片采样间隔（秒）")
    parser.add_argument("--log_interval",   type=float, default=DEFAULT_LOG_INTERVAL,
                        help="CSV 日志采样间隔（秒）")
    parser.add_argument("--output_dir",     default=DEFAULT_OUTPUT_ROOT,
                        help="会话输出根目录")
    parser.add_argument("--keyboard_device", default=None,
                        help="evdev 键盘设备路径（如 /dev/input/event3），None=自动发现")
    parser.add_argument("--serial_diag",    action="store_true",
                        help="串口诊断模式：打印原始串口包/计算vx wz/发送测试指令，不进入主控制循环")
    parser.add_argument("--diag_seconds",   type=float, default=10.0,
                        help="--serial_diag 运行时长（秒）")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = parse_args()
    if args.serial_diag:
        run_serial_diag(args)
    else:
        run_test(args)
