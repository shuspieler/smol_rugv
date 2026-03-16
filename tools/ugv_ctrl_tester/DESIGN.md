# UGV 控制通路验证工具 — 需求与设计文档

## 一、背景与目标

### 1.1 背景

`ugv_data_collector` 在采集正式训练数据前，需要先确认整条控制执行通路是否正常：
- 键盘输入能否被正确解析
- 速度指令能否通过串口到达底盘
- 底盘是否按预期运动
- 摄像头图像能否实时获取
- 底盘反馈数据（里程计、陀螺仪、电压）是否正常

`ugv_data_collector` 引入了 LeRobot 的 Dataset 接口，调试时负担过重、报错信息复杂，不适合初期通路验证。

### 1.2 目标

提供一个**极简的独立工具**，满足：
1. 键盘实时控制小车运动（前进、后退、转向、急停）
2. 简易抽样存储，直观确认控制效果：
   - 图片每 5 秒（可配置）保存一张 JPEG
   - 控制指令 + 底盘反馈每 1 秒（可配置）记录一行到 CSV
3. **零 LeRobot 依赖**，可在 LeRobot 未正确安装的情况下独立运行
4. 复用已有的 `robots/` 和 `teleop/` 代码，不重新实现串口逻辑

---

## 二、功能需求

### 2.1 核心需求

| # | 需求 | 验收标准 |
|---|------|---------|
| R1 | 键盘实时控制 | WASD 控制方向，QE 调速，Space 急停，Esc 退出 |
| R2 | 图片采样存储 | 每 `image_interval` 秒保存一张 JPEG 到 `images/` |
| R3 | 控制日志存储 | 每 `log_interval` 秒追加一行到 `ctrl_log.csv` |
| R4 | 终端实时反馈 | 单行原地刷新显示速度指令、反馈、电压、速度档 |
| R5 | 退出自动存档 | Esc/Ctrl+C 时自动保存最终帧再关闭串口 |
| R6 | 可配置参数 | 采样间隔、控制频率、串口、摄像头均可命令行覆盖 |
| R7 | dry_run 模式 | `--dry_run` 下用虚拟底盘和相机运行，不接真实硬件 |

### 2.2 明确不做

| 项目 | 原因 |
|------|------|
| LeRobot Dataset | 此工具仅验证通路，不采集训练数据 |
| Episode 管理 | 无数据集概念，运行到 Esc 为止 |
| 数据集上传 HF Hub | 同上 |
| 多目标任务标注 | 不需要 |

---

## 三、系统架构

```
键盘输入 (WASD)
       │
       ▼
KeyboardUGVTeleop         ← 复用 ugv_data_collector/teleop/
  .get_action()
       │  action = {"x.vel": float, "w.vel": float}
       ▼
UGVRover.send_action()    ← 复用 ugv_data_collector/robots/
       │         ──串口JSON──▶  ESP32 底盘
       ▼
UGVRover.get_observation()
       │  obs = { "x.vel", "w.vel", "observation.images.camera" }
       │  rover._latest_feedback = { odl, odr, gz, v, ... }
       ▼
ctrl_test.py 控制主循环（10Hz）
       ├── 每 log_interval(1s)  → 追加行到 ctrl_log.csv
       ├── 每 image_interval(5s) → 保存 JPEG
       └── 每帧              → \r 刷新终端状态行
```

---

## 四、数据记录格式

### 4.1 图片

- 格式：JPEG
- 文件名：`frame_<seq:05d>_<HHMMSS>.jpg`
- 分辨率：与 `ugv_config.yaml` 相机配置一致（默认 640×480）
- 颜色空间：BGR（OpenCV 写入标准）

### 4.2 控制日志 `ctrl_log.csv`

```
timestamp, elapsed_s, vx_cmd, wz_cmd, vx_actual, wz_actual, odl, odr, voltage_V, speed_scale, image_saved
```

| 字段 | 类型 | 来源 |
|------|------|------|
| `timestamp` | str (ISO ms) | `datetime.now()` |
| `elapsed_s` | float | `perf_counter() - session_start` |
| `vx_cmd` | float (m/s) | `teleop.get_action()["x.vel"]` |
| `wz_cmd` | float (rad/s) | `teleop.get_action()["w.vel"]` |
| `vx_actual` | float (m/s) | `UGVRover.get_observation()["x.vel"]`（里程计 diff 计算） |
| `wz_actual` | float (rad/s) | `UGVRover.get_observation()["w.vel"]`（陀螺仪计算） |
| `odl` / `odr` | int (tick) | `rover._latest_feedback["odl/odr"]` |
| `voltage_V` | float (V) | `rover._latest_feedback["v"] / 100` |
| `speed_scale` | float | `teleop.current_scale` |
| `image_saved` | 0/1 | 本行是否同步保存了图片 |

---

## 五、目录结构

```
tools/ugv_ctrl_tester/
├── DESIGN.md            ← 本文件
├── README.md            ← 快速使用说明
├── PROGRESS.md          ← 开发进度与测试记录
├── requirements.txt
├── ctrl_test.py         ← 主入口（单文件，~270行）
└── output/              ← 运行时自动生成
    └── <YYYYMMDD_HHMMSS>/
        ├── images/
        └── ctrl_log.csv
```

**不含** `robots/` 或 `teleop/` 目录——直接通过 `sys.path` 引用：
```python
_COLLECTOR_DIR = os.path.abspath("../ugv_data_collector")
sys.path.insert(0, _COLLECTOR_DIR)
from robots import UGVRover, UGVRoverConfig
from teleop import KeyboardUGVTeleop
```

---

## 六、配置来源与优先级

```
命令行参数  >  ugv_data_collector/config/ugv_config.yaml  >  程序内置默认值
```

| 参数 | 内置默认值 |
|------|-----------|
| `--serial_port` | `/dev/ttyTHS1` |
| `--camera_index` | `0` |
| `--control_hz` | `10` |
| `--image_interval` | `5.0` s |
| `--log_interval` | `1.0` s |
| `--output_dir` | `./output` |

---

## 七、依赖说明

| 依赖 | 版本 | 用途 |
|------|------|------|
| pyserial | >= 3.5 | 串口通信（经由 `UGVRover`） |
| opencv-python | >= 4.5 | 摄像头读取、JPEG 写入 |
| numpy | >= 1.21 | 图像数组 |
| pynput | >= 1.7 | 键盘监听（经由 `KeyboardUGVTeleop`） |
| PyYAML | >= 6.0 | 读取 `ugv_config.yaml` |

**无** lerobot 依赖。
