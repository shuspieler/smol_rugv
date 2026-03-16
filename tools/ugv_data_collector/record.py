#!/usr/bin/env python3
"""
record.py — UGV 数据采集主入口

使用键盘遥控 UGV Rover，将图像 + 状态 + 动作保存为 LeRobot 格式数据集。

用法：
    python record.py                          # 使用 config/ugv_config.yaml 的默认设置
    python record.py --dry_run               # 测试模式，不连接真实硬件
    python record.py --serial_port /dev/ttyCH341USB0 --repo_id myname/ugv-task --num_episodes 20

完整参数说明见 README.md 和 DESIGN.md。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径常量（模块加载时即确定，不依赖任何第三方库）
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "../.."))
_LEROBOT_SRC = os.environ.get("LEROBOT_SRC") or os.path.join(
    _PROJECT_ROOT, "ref_code", "lerobot-main (SmolVLA)", "src"
)

# 所有重量级 import（cv2, numpy, lerobot, robots, teleop）延迟到 run_recording() 内部执行，
# 以保证 `python record.py --help` 在依赖未完整安装时也能正常工作。

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
CONFIG_DEFAULT_PATH = os.path.join(_SCRIPT_DIR, "config", "ugv_config.yaml")

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("record")


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
        {key: {"dtype": str, "shape": list[int], "names": dict | list | None}}

    我们的特征：
        observation.state : float32, shape [2], dims=[vx, wz]
        action            : float32, shape [2], dims=[vx_cmd, wz_cmd]
        observation.images.camera : video, shape [H, W, 3]
    """
    return {
        "observation.state": {
            "dtype": "float32",
            "shape": [2],
            "names": ["x.vel", "w.vel"],
        },
        "action": {
            "dtype": "float32",
            "shape": [2],
            "names": ["x.vel", "w.vel"],
        },
        camera_key: {
            "dtype": "video",
            "shape": [camera_h, camera_w, 3],
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
    # 注入 LeRobot 路径
    if os.path.exists(_LEROBOT_SRC) and _LEROBOT_SRC not in sys.path:
        sys.path.insert(0, _LEROBOT_SRC)

    # 将本工具目录加入 sys.path，使 `from robots import ...` 可用
    if _SCRIPT_DIR not in sys.path:
        sys.path.insert(0, _SCRIPT_DIR)

    try:
        import numpy as np
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
        from robots import UGVRover, UGVRoverConfig
        from teleop import KeyboardUGVTeleop
    except ImportError as e:
        logger.error(f"Failed to import required modules: {e}")
        logger.error(f"  LEROBOT_SRC = {_LEROBOT_SRC}")
        logger.error("  Run: pip install -r requirements.txt")
        logger.error("  Ensure ref_code/lerobot-main (SmolVLA)/src/lerobot/ exists.")
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
    episode_end_event = [False]   # 使用列表以支持闭包修改

    def _on_episode_end():
        episode_end_event[0] = True

    quit_event = [False]

    def _on_quit():
        quit_event[0] = True

    # 加载遥控相关配置
    _cfg_raw = {}
    if os.path.exists(args.config):
        import yaml
        with open(args.config) as f:
            _cfg_raw = yaml.safe_load(f)

    teleop_cfg_raw = _cfg_raw.get("teleop", {})
    teleop = KeyboardUGVTeleop(
        max_linear=teleop_cfg_raw.get("max_linear", 0.5),
        max_angular=teleop_cfg_raw.get("max_angular", 1.5),
        speed_scales=teleop_cfg_raw.get("speed_scales"),
        default_scale_idx=teleop_cfg_raw.get("default_scale_idx", 1),
        on_episode_end=_on_episode_end,
        on_quit=_on_quit,
    )
    teleop.connect()
    logger.info("Keyboard teleop connected.")

    # --- 4. 创建 LeRobot Dataset ---
    features = build_lerobot_features(
        camera_key=config.camera_obs_key,
        camera_h=config.camera.height,
        camera_w=config.camera.width,
    )

    if output_dir.exists():
        logger.warning(
            f"Dataset directory already exists at {output_dir}. "
            "Will attempt to resume recording."
        )
        dataset = LeRobotDataset(repo_id=repo_id, root=output_dir)
        existing_episodes = dataset.meta.total_episodes
        logger.info(f"Resuming from episode {existing_episodes}")
    else:
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
            episode_end_event=episode_end_event,
            quit_event=quit_event,
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
    episode_end_event: list,
    quit_event: list,
) -> None:
    """逐 Episode 运行采集循环"""

    period = 1.0 / fps

    for ep_idx in range(existing_episodes, existing_episodes + num_episodes):
        if quit_event[0]:
            logger.info("Quit signal received. Stopping.")
            break

        _end_hint = "Enter=结束Episode, Esc=退出"
        logger.info(
            f"\n{'='*50}\n"
            f"  Episode {ep_idx + 1}/{existing_episodes + num_episodes}\n"
            f"  Task: {single_task}\n"
            f"  Speed scale: {teleop.current_scale:.1f} ({teleop.current_scale_idx + 1}/{len(teleop.speed_scales)})\n"
            f"  {_end_hint}\n"
            f"{'='*50}"
        )

        # 重置 episode 结束标志
        episode_end_event[0] = False

        # 采集当前 Episode
        frame_count = _record_one_episode(
            robot=robot,
            teleop=teleop,
            dataset=dataset,
            single_task=single_task,
            episode_time_s=episode_time_s,
            fps=fps,
            period=period,
            camera_key=camera_key,
            episode_end_event=episode_end_event,
            quit_event=quit_event,
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
        if ep_idx < existing_episodes + num_episodes - 1 and reset_time_s > 0:
            logger.info(
                f"\nReset phase: {reset_time_s}s to reset robot to start position.\n"
                "  Robot will not record during this time.\n"
                "  Press Enter to skip reset and start next episode immediately."
            )
            _wait_reset(
                robot=robot,
                teleop=teleop,
                reset_time_s=reset_time_s,
                period=period,
                episode_end_event=episode_end_event,
                quit_event=quit_event,
            )
            episode_end_event[0] = False


def _record_one_episode(
    robot,
    teleop,
    dataset,
    single_task: str,
    episode_time_s: float,
    fps: int,
    period: float,
    camera_key: str,
    episode_end_event: list,
    quit_event: list,
) -> int:
    """
    执行单个 Episode 的采集。
    返回实际采集的帧数。
    """
    import numpy as np  # 延迟导入，与 run_recording 中保持一致
    frame_count = 0
    start_time = time.perf_counter()

    while True:
        loop_start = time.perf_counter()

        # 检查终止条件
        elapsed = loop_start - start_time
        if elapsed >= episode_time_s:
            logger.info(f"Episode time limit reached ({episode_time_s}s).")
            break
        if episode_end_event[0]:
            logger.info("Episode ended by user (Enter key).")
            break
        if quit_event[0]:
            break

        # 1. 获取观测
        obs = robot.get_observation()

        # 2. 获取遥控动作
        action = teleop.get_action()

        # 3. 发送动作给小车
        sent_action = robot.send_action(action)

        # 4. 构建帧 dict（LeRobot 格式）
        #    - observation.state: [vx, wz] 当前底盘状态
        #    - action: [vx_cmd, wz_cmd] 操作员指令
        #    - camera_key: RGB 图像
        #    - task: 任务描述（字符串）
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
    episode_end_event: list,
    quit_event: list,
) -> None:
    """
    重置阶段：操作员控制小车回到起点，不录制数据。
    按 Enter 可提前跳过重置。
    """
    episode_end_event[0] = False
    start = time.perf_counter()
    while time.perf_counter() - start < reset_time_s:
        if episode_end_event[0] or quit_event[0]:
            break
        # 在重置阶段也允许遥控（方便回到起点）
        action = teleop.get_action()
        robot.send_action(action)
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

    args = parser.parse_args()

    # 从 yaml 补充未指定的参数
    if os.path.exists(args.config):
        import yaml
        with open(args.config) as f:
            raw = yaml.safe_load(f)
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
