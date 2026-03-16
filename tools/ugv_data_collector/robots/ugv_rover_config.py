"""
UGVRoverConfig — 小车硬件参数配置 dataclass

不依赖 draccus/LeRobot RobotConfig，直接使用 Python dataclass，
通过 ugv_config.yaml 或命令行参数在 record.py 中实例化。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UGVCameraConfig:
    """摄像头参数"""
    index: int = 0          # /dev/video{index}
    width: int = 640
    height: int = 480
    fps: int = 30


@dataclass
class UGVSerialConfig:
    """串口与底盘物理参数"""
    port: str = "/dev/ttyTHS1"
    baud: int = 115200
    timeout: float = 1.0
    # 底盘物理参数
    wheel_base: float = 0.235       # 轮距（m）
    wheel_radius: float = 0.045     # 轮半径（m）
    ticks_per_rev: int = 1320       # 编码器每圈脉冲数（保留，暂未使用）


@dataclass
class UGVRoverConfig:
    """UGV Rover 完整配置"""
    serial: UGVSerialConfig = field(default_factory=UGVSerialConfig)
    camera: UGVCameraConfig = field(default_factory=UGVCameraConfig)
    # 相机在 LeRobot 数据集中的 key，必须与训练时一致
    camera_obs_key: str = "observation.images.camera"
    # 是否启用 dry_run 模式（跳过真实硬件）
    dry_run: bool = False
    # robot id（用于日志标识）
    robot_id: str = "ugv_rover"

    @classmethod
    def from_yaml(cls, path: str) -> "UGVRoverConfig":
        """从 ugv_config.yaml 加载配置"""
        import yaml
        with open(path) as f:
            raw = yaml.safe_load(f)

        serial_raw = raw.get("serial", {})
        camera_raw = raw.get("camera", {})

        return cls(
            serial=UGVSerialConfig(
                port=serial_raw.get("port", "/dev/ttyTHS1"),
                baud=serial_raw.get("baud", 115200),
                timeout=serial_raw.get("timeout", 1.0),
                wheel_base=serial_raw.get("wheel_base", 0.235),
                wheel_radius=serial_raw.get("wheel_radius", 0.045),
                ticks_per_rev=serial_raw.get("ticks_per_rev", 1320),
            ),
            camera=UGVCameraConfig(
                index=camera_raw.get("index", 0),
                width=camera_raw.get("width", 640),
                height=camera_raw.get("height", 480),
                fps=camera_raw.get("fps", 30),
            ),
        )
