# UGV 控制通路验证工具 (`ugv_ctrl_tester`)

轻量级工具，用于**快速验证从键盘输入到小车实际运动的完整控制通路**，不依赖 LeRobot 或 ROS2。

详细需求与设计见 [DESIGN.md](DESIGN.md)，开发状态见 [PROGRESS.md](PROGRESS.md)。

---

## 功能概述

| 功能 | 说明 |
|---|---|
| 键盘实时控制 | WASD 前后左右，QE 调速，Space 急停，Esc 退出 |
| 图片采样存储 | 每 N 秒（默认 5s）保存一张摄像头 JPEG |
| 控制日志记录 | 每 N 秒（默认 1s）追加一行到 `ctrl_log.csv` |
| 终端实时状态 | 原地刷新显示速度指令、底盘反馈、电压、速度档 |
| 无 LeRobot 依赖 | 完全独立，仅用 pyserial / opencv / pynput |

---

## 快速开始

### 1. 安装依赖

```bash
cd tools/ugv_ctrl_tester
pip install -r requirements.txt
```

### 2. 运行

```bash
# 连接真实硬件（使用 ugv_data_collector 的 ugv_config.yaml 中的串口/相机配置）
python ctrl_test.py

# 覆盖串口和摄像头
python ctrl_test.py --serial_port /dev/ttyCH341USB0 --camera_index 0

# 不连接真实硬件（调试流程）
python ctrl_test.py --dry_run

# 自定义采样间隔
python ctrl_test.py --image_interval 10 --log_interval 2
```

### 3. 键盘操作

| 按键 | 动作 |
|------|------|
| `W` | 前进 |
| `S` | 后退 |
| `A` | 左转 |
| `D` | 右转 |
| `Q` | 提高速度档 |
| `E` | 降低速度档 |
| `Space` | **急停**（发送零速度指令） |
| `Esc` / `Ctrl+C` | 保存最终帧并退出 |

---

## 输出结构

每次运行在 `output/<YYYYMMDD_HHMMSS>/` 下生成：

```
output/
└── 20260310_143022/
    ├── images/
    │   ├── frame_00000_143022.jpg
    │   ├── frame_00001_143027.jpg
    │   └── frame_00002_final.jpg      ← 退出时自动保存最后一帧
    └── ctrl_log.csv
```

### `ctrl_log.csv` 格式

| 字段 | 说明 |
|------|------|
| `timestamp` | 记录时间（ms 精度） |
| `elapsed_s` | 距会话开始的秒数 |
| `vx_cmd` | 键盘指令线速度（m/s） |
| `wz_cmd` | 键盘指令角速度（rad/s） |
| `vx_actual` | 底盘反馈线速度（m/s，由里程计计算） |
| `wz_actual` | 底盘反馈角速度（rad/s，由陀螺仪计算） |
| `odl` / `odr` | 左/右轮里程计原始值（tick） |
| `voltage_V` | 电池电压（V） |
| `speed_scale` | 当前速度档（0.1 ~ 1.0） |
| `image_saved` | 本行是否同步保存了图片（1=是） |

---

## 命令行参数速查

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--serial_port` | `ugv_config.yaml` 中的值 | 串口设备路径 |
| `--camera_index` | `ugv_config.yaml` 中的值 | 摄像头 `/dev/videoN` |
| `--dry_run` | `False` | 不连接真实硬件 |
| `--control_hz` | `10` | 控制循环频率（Hz） |
| `--image_interval` | `5.0` | 图片采样间隔（秒） |
| `--log_interval` | `1.0` | CSV 日志采样间隔（秒） |
| `--output_dir` | `./output` | 会话输出根目录 |

---

## 硬件配置

本工具自动读取 `../ugv_data_collector/config/ugv_config.yaml` 中的串口和相机参数。
如未找到该文件，使用内置默认值（串口 `/dev/ttyCH341USB0`，摄像头 `/dev/video0`）。

如需修改，直接编辑 `ugv_data_collector` 的 `ugv_config.yaml`，或通过命令行参数覆盖。

---

## 与 `ugv_data_collector` 的关系

| 项目 | `ugv_ctrl_tester` | `ugv_data_collector` |
|---|---|---|
| 目的 | **验证控制通路** | 采集训练数据集 |
| 存储 | 简易图片 + CSV | LeRobot 数据集（parquet + video） |
| LeRobot 依赖 | **无** | 有 |
| Episode 管理 | 无 | 有 |
| 适用阶段 | 硬件调试、效果验证 | 正式数据采集 |

代码层面：`ctrl_test.py` 直接复用 `ugv_data_collector` 的 `robots/` 和 `teleop/` 模块，无重复实现。
