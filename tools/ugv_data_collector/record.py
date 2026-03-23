#!/usr/bin/env python3
"""
record.py — UGV 数据采集主入口

使用键盘遥控 UGV Rover，将图像 + 状态 + 动作保存为 LeRobot 格式数据集。

用法：
    python record.py                          # 默认：手动 Enter 控制每个 episode
    python record.py --auto                   # 自动定时采集（episode_time_s 到时自动结束）
    python record.py --dry_run               # 测试模式，不连接真实硬件
    python record.py --serial_port /dev/ttyCH341USB0 --repo_id myname/ugv-task --num_episodes 20

完整参数说明见 README.md 和 DESIGN.md。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径常量（模块加载时即确定，不依赖任何第三方库）
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "../.."))

# 可选的本地 LeRobot 开发路径（仅当需要修改 LeRobot 源码时设置）
_LEROBOT_SRC = os.environ.get("LEROBOT_SRC", None)

# 如果显式指定了本地路径但不存在，记录警告
if _LEROBOT_SRC and not os.path.exists(_LEROBOT_SRC):
    logger_init = logging.getLogger("record")
    logger_init.warning(f"LEROBOT_SRC 指向的路径不存在: {_LEROBOT_SRC}")
    _LEROBOT_SRC = None

# 所有重量级 import（cv2, numpy, lerobot, robots, teleop）延迟到 run_recording() 内部执行，
# 以保证 `python record.py --help` 在依赖未完整安装时也能正常工作。

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
CONFIG_DEFAULT_PATH = os.path.join(_SCRIPT_DIR, "config", "ugv_config.yaml")

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("record")


# ---------------------------------------------------------------------------
# MJPEG 实时预览（浏览器访问，适用于无头/SSH 环境）
# ---------------------------------------------------------------------------

_mjpeg_frame_lock = threading.Lock()
_mjpeg_latest_jpg: bytes = b""
_mjpeg_server_started = False


def _start_mjpeg_server(port: int = 8080) -> None:
    """启动后台 MJPEG HTTP 服务，仅启动一次。"""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    global _mjpeg_server_started
    if _mjpeg_server_started:
        return

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # 静默 HTTP 日志
            pass

        def do_GET(self):
            if self.path in ("/", "/stream"):
                self.send_response(200)
                self.send_header("Content-Type",
                                 "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                try:
                    while True:
                        with _mjpeg_frame_lock:
                            jpg = _mjpeg_latest_jpg
                        if jpg:
                            self.wfile.write(
                                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                                + jpg + b"\r\n"
                            )
                        time.sleep(0.033)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
            else:
                self.send_response(404)
                self.end_headers()

    srv = HTTPServer(("0.0.0.0", port), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True, name="mjpeg-server")
    t.start()
    _mjpeg_server_started = True
    # 获取本机局域网 IP
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        lan_ip = "<机器人IP>"
    logger.info(
        f"\n📷 摄像头预览已启动，在同局域网的浏览器打开：\n"
        f"   http://{lan_ip}:{port}/stream"
    )


def _preview_frame(frame_rgb, label: str, is_recording: bool = False) -> None:
    """
    将一帧画面编码为 JPEG 并推入 MJPEG 流（不依赖 GUI/GTK）。
    frame_rgb: numpy (H, W, 3) uint8，RGB 格式。
    """
    import cv2
    global _mjpeg_latest_jpg
    frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    text = f"{'[REC]' if is_recording else '[READY]'}  {label}"
    color = (0, 60, 220) if is_recording else (0, 200, 60)
    cv2.putText(frame_bgr, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 3)
    cv2.putText(frame_bgr, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2)
    ret, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if ret:
        with _mjpeg_frame_lock:
            _mjpeg_latest_jpg = buf.tobytes()


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def build_lerobot_features(
    camera_key: str,
    camera_h: int,
    camera_w: int,
) -> dict:
    """
    返回符合 LeRobot 格式要求的 features 字典。

    LeRobot features 格式：
        {key: {"dtype": str, "shape": tuple[int, ...], "names": dict | list | None}}

    注意：shape 必须使用 tuple 而非 list，因为 LeRobotDataset.create() 不会
    像 load_info() 那样自动将 list 转为 tuple，导致 validate_frame() 中
    numpy.shape (tuple) 与 features.shape (list) 比较失败。
    """
    return {
        "observation.state": {
            "dtype": "float32",
            "shape": (2,),
            "names": ["x.vel", "w.vel"],
        },
        "action": {
            "dtype": "float32",
            "shape": (2,),
            "names": ["x.vel", "w.vel"],
        },
        camera_key: {
            "dtype": "video",
            "shape": (camera_h, camera_w, 3),
            "names": ["height", "width", "channel"],
        },
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_recording(args: argparse.Namespace) -> None:
    """
    完整采集流程：
      1. 加载配置
      2. 初始化 Robot + Teleop + Dataset
      3. 逐 Episode 采集
      4. 保存并（可选）上传
    """
    # --- 0. 延迟导入重量级依赖 ---
    # 如果显式指定了本地 LeRobot 源码，优先使用
    if _LEROBOT_SRC:
        if _LEROBOT_SRC not in sys.path:
            sys.path.insert(0, _LEROBOT_SRC)
        logger.info(f"Using local LeRobot from: {_LEROBOT_SRC}")
    # 否则使用通过 pip 安装的 lerobot（默认行为）

    # 将本工具目录加入 sys.path，使 `from robots import ...` 可用
    if _SCRIPT_DIR not in sys.path:
        sys.path.insert(0, _SCRIPT_DIR)

    try:
        import numpy as np
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
        from robots import UGVRover, UGVRoverConfig
        from teleop import EvdevUGVTeleop
    except ImportError as e:
        logger.error(f"Failed to import required modules: {e}")
        if _LEROBOT_SRC:
            logger.error(f"  LEROBOT_SRC = {_LEROBOT_SRC}")
        logger.error("  Run: python -m pip install -r requirements.txt")
        if not _LEROBOT_SRC:
            logger.error("  Or: python -m pip install lerobot")
        sys.exit(1)

    # --- 1. 加载配置 ---
    if os.path.exists(args.config):
        config = UGVRoverConfig.from_yaml(args.config)
        logger.info(f"Loaded config from {args.config}")
    else:
        config = UGVRoverConfig()
        logger.warning(f"Config file not found at {args.config}, using defaults.")

    # 命令行参数优先覆盖 yaml
    if args.serial_port:
        config.serial.port = args.serial_port
    if args.camera_index is not None:
        config.camera.index = args.camera_index
    if args.dry_run:
        config.dry_run = True

    # 数据集参数
    repo_id = args.repo_id
    single_task = args.single_task
    num_episodes = args.num_episodes
    episode_time_s = args.episode_time_s
    reset_time_s = args.reset_time_s
    fps = config.camera.fps
    output_dir = Path(args.output_dir) / repo_id

    logger.info(
        f"Recording config:\n"
        f"  repo_id       = {repo_id}\n"
        f"  task          = {single_task}\n"
        f"  episodes      = {num_episodes}\n"
        f"  episode_time  = {episode_time_s}s\n"
        f"  reset_time    = {reset_time_s}s\n"
        f"  fps           = {fps}\n"
        f"  output_dir    = {output_dir}\n"
        f"  serial_port   = {config.serial.port}\n"
        f"  camera_index  = {config.camera.index}\n"
        f"  dry_run       = {config.dry_run}"
    )

    # --- 2. 初始化 Robot ---
    robot = UGVRover(config)
    robot.connect()
    logger.info("Robot connected.")

    # --- 3. 初始化键盘遥控 ---
    quit_event = [False]

    def _on_quit():
        quit_event[0] = True

    # 加载遥控相关配置
    _cfg_raw = {}
    if os.path.exists(args.config):
        import yaml
        with open(args.config) as f:
            _cfg_raw = yaml.safe_load(f) or {}

    # enter_event: 手动模式下的 Enter 键共享标志，evdev 回调设置它
    _enter_event = [False]
    _enter_lock = threading.Lock()

    def _on_enter():
        with _enter_lock:
            _enter_event[0] = True

    teleop_cfg_raw = _cfg_raw.get("teleop", {})
    teleop = EvdevUGVTeleop(
        max_linear=teleop_cfg_raw.get("max_linear", 0.5),
        max_angular=teleop_cfg_raw.get("max_angular", 1.5),
        speed_scales=teleop_cfg_raw.get("speed_scales"),
        default_scale_idx=teleop_cfg_raw.get("default_scale_idx", 1),
        on_quit=_on_quit,
        on_enter=_on_enter,
        device_path=args.keyboard_device,
    )
    teleop.connect()
    logger.info("Evdev keyboard teleop connected (WASD/QE/Space/Esc).")

    # --- 4. 创建 LeRobot Dataset ---
    features = build_lerobot_features(
        camera_key=config.camera_obs_key,
        camera_h=config.camera.height,
        camera_w=config.camera.width,
    )

    # 对于 dry_run 模式，总是创建新数据集（不尝试恢复）
    if output_dir.exists() and not config.dry_run:
        logger.warning(
            f"Dataset directory already exists at {output_dir}. "
            "Will attempt to resume recording."
        )
        try:
            dataset = LeRobotDataset(repo_id=repo_id, root=output_dir)
            existing_episodes = dataset.meta.total_episodes
            logger.info(f"Resuming from episode {existing_episodes}")
        except Exception as e:
            logger.warning(f"Failed to resume dataset: {e}. Creating new dataset instead.")
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)
            dataset = LeRobotDataset.create(
                repo_id=repo_id,
                fps=fps,
                features=features,
                robot_type="ugv_rover",
                root=output_dir,
            )
            existing_episodes = 0
            logger.info("New dataset created.")
    else:
        if output_dir.exists() and config.dry_run:
            logger.info("Dry run mode: clearing dataset directory for fresh test.")
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)
        
        dataset = LeRobotDataset.create(
            repo_id=repo_id,
            fps=fps,
            features=features,
            robot_type="ugv_rover",
            root=output_dir,
        )
        existing_episodes = 0
        logger.info("New dataset created.")

    # --- 5. 主采集循环 ---
    if args.preview and not config.dry_run:
        _start_mjpeg_server()
    try:
        _record_all_episodes(
            robot=robot,
            teleop=teleop,
            dataset=dataset,
            single_task=single_task,
            num_episodes=num_episodes,
            existing_episodes=existing_episodes,
            episode_time_s=episode_time_s,
            reset_time_s=reset_time_s,
            fps=fps,
            camera_key=config.camera_obs_key,
            quit_event=quit_event,
            enter_event=_enter_event,
            enter_lock=_enter_lock,
            manual_control=not args.auto,
            preview=args.preview and not config.dry_run,
        )
    finally:
        # --- 6. 清理与保存 ---
        logger.info("Finalizing dataset...")
        dataset.finalize()
        logger.info(f"Dataset saved to {output_dir}")

        if args.push_to_hub:
            logger.info("Pushing dataset to HuggingFace Hub...")
            dataset.push_to_hub()

        teleop.disconnect()
        robot.disconnect()
        logger.info("Done.")


def _record_all_episodes(
    robot,
    teleop,
    dataset,
    single_task: str,
    num_episodes: int,
    existing_episodes: int,
    episode_time_s: float,
    reset_time_s: float,
    fps: int,
    camera_key: str,
    quit_event: list,
    enter_event: list | None = None,
    enter_lock=None,
    manual_control: bool = False,
    preview: bool = False,
) -> None:
    """逐 Episode 运行采集循环"""

    period = 1.0 / fps

    def _reset_enter():
        """清除 enter_event，准备下一次等待"""
        if enter_event is not None and enter_lock is not None:
            with enter_lock:
                enter_event[0] = False

    def _wait_enter():
        """阻塞等待 Enter 键被按下（或 Esc 退出）"""
        while not (enter_event and enter_event[0]) and not quit_event[0]:
            action = teleop.get_action()
            robot.send_action(action)
            if preview:
                obs = robot.get_observation()
                _preview_frame(obs[camera_key], "Press Enter to start", is_recording=False)
            else:
                time.sleep(period)

    for ep_idx in range(existing_episodes, existing_episodes + num_episodes):
        if quit_event[0]:
            logger.info("Quit signal received. Stopping.")
            break

        # --- 手动模式：等待 Enter 开始录制 ---
        if manual_control:
            _reset_enter()  # 确保上一次 Enter 不影响本次等待
            logger.info(
                f"\n{'='*50}\n"
                f"  Episode {ep_idx + 1}/{existing_episodes + num_episodes}\n"
                f"  Task: {single_task}\n"
                f"  Speed scale: {teleop.current_scale:.1f} ({teleop.current_scale_idx + 1}/{len(teleop.speed_scales)})\n"
                f"  [手动模式] 移动机器人到起始位置，按 Enter 开始录制 | Esc=退出\n"
                f"{'='*50}"
            )
            _wait_enter()
            if quit_event[0]:
                break
            logger.info("  ▶ 开始录制... 完成后再按 Enter 结束本 episode")
            _reset_enter()  # 清除刚才的 Enter，准备等待结束信号
        else:
            logger.info(
                f"\n{'='*50}\n"
                f"  Episode {ep_idx + 1}/{existing_episodes + num_episodes}\n"
                f"  Task: {single_task}\n"
                f"  Speed scale: {teleop.current_scale:.1f} ({teleop.current_scale_idx + 1}/{len(teleop.speed_scales)})\n"
                f"  Esc=退出\n"
                f"{'='*50}"
            )

        # 采集当前 Episode
        frame_count = _record_one_episode(
            robot=robot,
            teleop=teleop,
            dataset=dataset,
            single_task=single_task,
            episode_index=ep_idx,
            episode_time_s=episode_time_s,
            fps=fps,
            period=period,
            camera_key=camera_key,
            quit_event=quit_event,
            enter_end_event=enter_event if manual_control else None,
            preview=preview,
        )

        if frame_count == 0:
            logger.warning(f"Episode {ep_idx} had 0 frames, skipping save.")
            continue

        # 保存当前 Episode
        logger.info(f"Saving episode {ep_idx} ({frame_count} frames)...")
        dataset.save_episode()
        logger.info(f"Episode {ep_idx} saved.")

        if quit_event[0]:
            break

        # 重置阶段（让操作员回到初始位置）
        # 手动模式下跳过计时重置（下一个 episode 开始前已有 Enter 等待作为缓冲）
        if not manual_control and ep_idx < existing_episodes + num_episodes - 1 and reset_time_s > 0:
            logger.info(
                f"\nReset phase: {reset_time_s}s to reset robot to start position.\n"
                "  Robot will not record during this time.\n"
                "  Press Esc to stop recording immediately."
            )
            _wait_reset(
                robot=robot,
                teleop=teleop,
                reset_time_s=reset_time_s,
                period=period,
                quit_event=quit_event,
                preview=preview,
                camera_key=camera_key,
            )


def _record_one_episode(
    robot,
    teleop,
    dataset,
    single_task: str,
    episode_index: int,
    episode_time_s: float,
    fps: int,
    period: float,
    camera_key: str,
    quit_event: list,
    enter_end_event: list | None = None,
    preview: bool = False,
) -> int:
    """
    执行单个 Episode 的采集。
    返回实际采集的帧数。
    enter_end_event: 若不为 None（手动模式），按 Enter 结束本 episode，忽略时间限制。
    """
    import numpy as np  # 延迟导入，与 run_recording 中保持一致
    frame_count = 0
    start_time = time.perf_counter()

    while True:
        loop_start = time.perf_counter()

        # 检查终止条件
        elapsed = loop_start - start_time
        if enter_end_event is not None:
            # 手动模式：Enter 键结束
            if enter_end_event[0]:
                logger.info(f"Episode ended by Enter key ({elapsed:.1f}s, {frame_count} frames).")
                break
        else:
            # 自动模式：时间到结束
            if elapsed >= episode_time_s:
                logger.info(f"Episode time limit reached ({episode_time_s}s).")
                break
        if quit_event[0]:
            break

        # 1. 获取观测
        obs = robot.get_observation()

        # 实时预览
        if preview:
            _preview_frame(
                obs[camera_key],
                f"ep {episode_index + 1}  frame {frame_count}  t={elapsed:.1f}s",
                is_recording=True,
            )

        # 2. 获取遥控动作
        action = teleop.get_action()

        # 3. 发送动作给小车
        sent_action = robot.send_action(action)

        # 4. 构建帧 dict（LeRobot 格式）
        #    - observation.state: [vx, wz] 当前底盘状态
        #    - action: [vx_cmd, wz_cmd] 操作员指令
        #    - camera_key: RGB 图像
        #    - task: 任务描述（字符串）
        # 注意：LeRobot 会自动添加 timestamp, frame_index, episode_index 等元数据
        frame = {
            "observation.state": np.array(
                [obs["x.vel"], obs["w.vel"]], dtype=np.float32
            ),
            "action": np.array(
                [sent_action["x.vel"], sent_action["w.vel"]], dtype=np.float32
            ),
            camera_key: obs[camera_key],   # numpy (H, W, 3) uint8 RGB
            "task": single_task,
        }

        # 5. 添加到 dataset
        dataset.add_frame(frame)
        frame_count += 1

        # 6. 定频控制（保持 fps）
        elapsed_loop = time.perf_counter() - loop_start
        sleep_time = period - elapsed_loop
        if sleep_time > 0:
            time.sleep(sleep_time)

        # 7. 状态打印（每秒一次）
        if frame_count % fps == 0:
            logger.info(
                f"  t={elapsed:.1f}s | frame={frame_count} | "
                f"vx={obs['x.vel']:.2f} wz={obs['w.vel']:.2f} | "
                f"cmd_vx={sent_action['x.vel']:.2f} cmd_wz={sent_action['w.vel']:.2f} | "
                f"scale={teleop.current_scale:.1f}"
            )

    return frame_count


def _wait_reset(
    robot,
    teleop,
    reset_time_s: float,
    period: float,
    quit_event: list,
    preview: bool = False,
    camera_key: str = "observation.images.camera",
) -> None:
    """
    重置阶段：操作员控制小车回到起点，不录制数据。
    按 Esc 可退出采集。
    """
    start = time.perf_counter()
    while time.perf_counter() - start < reset_time_s:
        if quit_event[0]:
            break
        # 在重置阶段也允许遥控（方便回到起点）
        action = teleop.get_action()
        robot.send_action(action)
        if preview:
            obs = robot.get_observation()
            remaining = reset_time_s - (time.perf_counter() - start)
            _preview_frame(
                obs[camera_key],
                f"RESET  {remaining:.0f}s remaining",
                is_recording=False,
            )
        else:
            time.sleep(period)


# ---------------------------------------------------------------------------
# 命令行参数解析
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="UGV LeRobot 数据采集工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # -- 配置文件 --
    parser.add_argument(
        "--config",
        default=CONFIG_DEFAULT_PATH,
        help="ugv_config.yaml 路径，命令行参数优先级更高",
    )

    # -- 硬件参数（覆盖 yaml） --
    parser.add_argument("--serial_port", default=None, help="串口设备路径，如 /dev/ttyCH341USB0")
    parser.add_argument("--camera_index", type=int, default=None, help="摄像头 /dev/videoN 序号")
    parser.add_argument("--dry_run", action="store_true", help="跳过真实串口和摄像头（调试用）")
    parser.add_argument(
        "--preview",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="录制时同步弹出摄像头预览窗口（dry_run 下自动关闭）",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        default=False,
        help="自动定时采集：每个 episode 到达 episode_time_s 后自动结束（默认为手动 Enter 控制）",
    )

    # -- 数据集参数（覆盖 yaml） --
    parser.add_argument(
        "--repo_id",
        default=None,
        help="数据集 ID，格式：{hf_username}/{dataset_name}",
    )
    parser.add_argument("--single_task", default=None, help="任务描述文本")
    parser.add_argument("--num_episodes", type=int, default=None, help="采集的 Episode 数量")
    parser.add_argument("--episode_time_s", type=float, default=None, help="每个 Episode 的最长采集时间（秒）")
    parser.add_argument("--reset_time_s", type=float, default=None, help="Episode 间重置时间（秒）")
    parser.add_argument("--output_dir", default=None, help="数据集输出目录")
    parser.add_argument("--push_to_hub", action="store_true", help="采集完成后上传到 HuggingFace Hub")
    parser.add_argument(
        "--keyboard_device",
        default=None,
        help="evdev 键盘设备路径（如 /dev/input/event3），为空时自动发现",
    )

    args = parser.parse_args()

    # 从 yaml 补充未指定的参数
    if os.path.exists(args.config):
        import yaml
        with open(args.config) as f:
            raw = yaml.safe_load(f) or {}
        ds = raw.get("dataset", {})

        if args.repo_id is None:
            args.repo_id = ds.get("repo_id", "myusername/ugv-dataset")
        if args.single_task is None:
            args.single_task = ds.get("single_task", "Follow the person in front of the robot")
        if args.num_episodes is None:
            args.num_episodes = ds.get("num_episodes", 20)
        if args.episode_time_s is None:
            args.episode_time_s = ds.get("episode_time_s", 30)
        if args.reset_time_s is None:
            args.reset_time_s = ds.get("reset_time_s", 10)
        if args.output_dir is None:
            args.output_dir = ds.get("output_dir", "./datasets")
        if not args.push_to_hub:
            args.push_to_hub = ds.get("push_to_hub", False)
    else:
        # 默认值
        if args.repo_id is None:
            args.repo_id = "myusername/ugv-dataset"
        if args.single_task is None:
            args.single_task = "Follow the person in front of the robot"
        if args.num_episodes is None:
            args.num_episodes = 20
        if args.episode_time_s is None:
            args.episode_time_s = 30
        if args.reset_time_s is None:
            args.reset_time_s = 10
        if args.output_dir is None:
            args.output_dir = "./datasets"

    return args


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = parse_args()
    try:
        run_recording(args)
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user (Ctrl+C). Exiting.")
        sys.exit(0)
