# UGV 数据采集工具 — 需求与设计文档

## 零、环境与依赖

**前置要求**：
- Python >= 3.10（推荐使用 conda 环境隔离）
- LeRobot 框架（v0.4.0+）：
  ```bash
  python -m pip install lerobot
  # 若同时需要 SmolVLA 训练功能
  python -m pip install "lerobot[smolvla]"
  ```

**本工具无需额外克隆源码**，通过 pip 安装的 LeRobot 库自动包含所需的数据集操作、采集循环等接口。

若需要修改 LeRobot 源码进行二次开发，可选择本地克隆方案（见 README.md 中的可选项）。

---

## 一、背景与目标

本工具为 `smol_rugv` 项目的独立数据采集模块，**不依赖 ROS2**，纯 Python 运行。

目标：在 LeRobot 框架下，通过**键盘**遥控 UGV Rover 小车，将采集到的：
- 摄像头图像（RGB）
- 底盘状态（线速度 vx、角速度 wz）
- 操作员动作（目标线速度、目标角速度）

保存为标准 LeRobot 数据集格式（HuggingFace），用于后续 SmolVLA 模型微调训练。

---

## 二、功能需求

### 2.1 核心功能
| # | 功能 | 说明 |
|---|------|------|
| F1 | 键盘遥控小车 | WASD 控制方向，QE 调节速度档，Space 急停 |
| F2 | 同步采集图像 | USB 摄像头，640×480 @ 30fps，RGB |
| F3 | 同步采集底盘状态 | 串口读取 ESP32 反馈（线速度 vx、角速度 wz） |
| F4 | 记录操作员动作 | 遥控输入映射为 [vx, wz] 存入数据集 |
| F5 | 分 Episode 管理 | **默认**：Enter 键手动开始/结束；`--auto` 模式下按设定时长自动结束 |
| F6 | 本地存储数据集 | 保存为 LeRobotDataset 格式到本地路径 |
| F7 | 可选上传 HF Hub | 采集完毕后可选择 push 到 HuggingFace |
| F8 | MJPEG 实时预览 | 部署 HTTP 流，浏览器访问 http://\<LAN-IP\>:8080/stream 查看实时画面 |

### 2.2 安全需求
| # | 需求 | 说明 |
|---|------|------|
| S1 | 急停 | 按 Space 立即发送零速度命令 |
| S2 | 退出时刹停 | `disconnect()` 时发送零速度后再关闭串口 |
| S3 | 串口超时保护 | 读取超时不抛出异常，仅记录日志并使用上次状态 |

---

## 三、系统架构

```
键盘输入 (WASD)
          │
          ▼
 EvdevUGVTeleop
  .get_action()
          │  action = {"x.vel": float, "w.vel": float}
          ▼
         UGVRover.send_action(action)  ──串口JSON──▶  ESP32 底盘
                     │
                     │  同时调用
                     ▼
         UGVRover.get_observation()
                     │  obs = {
                     │      "x.vel": float,           # 从底盘反馈读取
                     │      "w.vel": float,
                     │      "observation.images.camera": np.ndarray(H,W,3)
                     │  }
                     ▼
         LeRobot record_loop()
                     │
                     ▼
         LeRobotDataset  (本地 parquet + 视频文件)
```

---

## 四、接口规范

### 4.1 观测空间（observation_features）

| Key | 类型 | 说明 |
|-----|------|------|
| `x.vel` | `float` | 底盘当前线速度（m/s），从串口反馈计算 |
| `w.vel` | `float` | 底盘当前角速度（rad/s），从串口反馈计算 |
| `observation.images.camera` | `(480, 640, 3)` | RGB 图像，uint8 |

### 4.2 动作空间（action_features）

| Key | 类型 | 说明 |
|-----|------|------|
| `x.vel` | `float` | 目标线速度（m/s），范围 [-max_linear, max_linear] |
| `w.vel` | `float` | 目标角速度（rad/s），范围 [-max_angular, max_angular] |

> **重要对齐说明**：`observation.images.camera` 这个 key 需与 `src/vla/vla/inference/preprocess.py` 中的 `self.image_key` 保持一致。训练完成部署时需将 `preprocess.py` 中的 key 从 `"observation.images.laptop"` 改为 `"observation.images.camera"`。

### 4.3 串口协议

**发送（控制命令）**
```json
{"T": "13", "X": 0.3, "Z": 0.5}
```
- `T`: 命令类型，固定 `"13"`（来自 waveshare ugv 协议）
- `X`: 线速度 linear_x（m/s）
- `Z`: 角速度 angular_z（rad/s）

**接收（状态反馈）**
```json
{"T": 1001, "L": ..., "R": ..., "ax": ..., "ay": ..., "az": ..., "gx": ..., "gy": ..., "gz": ..., "odl": ..., "odr": ..., "v": ...}
```
- `odl`/`odr`: 左右轮里程计增量（**cm**，ESP32 内部已由 tick 转换）
- `gx`/`gy`/`gz`: 陀螺仪角速度（deg/s）
- 由里程计增量 + 轮距参数计算 vx 和 wz

---

## 五、遥控控制映射

### 5.1 键盘操作

| 按键 | 动作 |
|------|------|
| `W` | 前进（+linear） |
| `S` | 后退（-linear） |
| `A` | 左转（+angular） |
| `D` | 右转（-angular） |
| `Q` | 提高速度档 |
| `E` | 降低速度档 |
| `Space` | 急停（发送零速度） |
| `Enter` | 开始录制 / 结束当前 episode（手动模式） |
| `Esc` / `Ctrl+C` | 退出采集 |

速度档（scale）：`[0.1, 0.2, 0.3, 0.5, 0.7, 1.0]`，默认从第 2 档（0.2）开始。

---

## 六、目录结构

```
tools/ugv_data_collector/
├── DESIGN.md                    # 本文件：需求与设计文档
├── README.md                    # 快速使用说明
├── requirements.txt             # Python 依赖
├── config/
│   └── ugv_config.yaml          # 运行参数（串口、相机、键盘、数据集配置）
├── robots/
│   ├── __init__.py
│   ├── ugv_rover_config.py      # UGVRoverConfig dataclass
│   └── ugv_rover.py             # UGVRover(Robot) — 适配 LeRobot 接口
├── teleop/
│   ├── __init__.py
│   ├── evdev_teleop.py          # EvdevUGVTeleop — 键盘遥控器（复用 ugv_ctrl_tester 可行方案）
└── record.py                    # 主入口脚本
```

---

## 七、运行方式

```bash
cd tools/ugv_data_collector

# 默认：手动 Enter 控制录制（推荐）
python record.py \
      --serial_port /dev/ttyCH341USB0 \
  --camera_index 0 \
  --repo_id myname/ugv-follow-task \
  --single_task "Follow the person" \
  --num_episodes 20 \
  --output_dir ./datasets

# 自动定时模式（episode_time_s 到时自动结束）
python record.py --auto --episode_time_s 30

# 关闭摄像头预览（默认 http://<LAN-IP>:8080/stream）
python record.py --no-preview

# 测试模式（不连接真实硬件，用于调试）
python record.py --dry_run
```

---

## 八、与主工程的关系与部署流程

```
[本工具] 键盘遥控采集
      ↓ 产出
datasets/ugv-follow-task/          ← LeRobot 格式数据集

[外部 LeRobot 训练环境（PC/服务器）]
lerobot-train --dataset.repo_id=myname/ugv-follow-task ...
      ↓ 产出
model_weights/smolvla_ugv_finetuned/

[主工程部署]
src/vla/vla/model/smol_vla_policy.py  ← 加载微调后权重
src/vla/vla/inference/preprocess.py   ← 将 image_key 改为 "observation.images.camera"
```

### 8.1 部署时主工程需要的修改

修改 `src/vla/vla/inference/preprocess.py`：
```python
# 修改前
self.image_key = "observation.images.laptop"
# 修改后
self.image_key = "observation.images.camera"
```

修改 `src/smol_bringup/config/model.yaml`：
```yaml
model_id: "local:///path/to/smolvla_ugv_finetuned"
```

---

## 九、依赖说明

| 依赖 | 版本要求 | 安装方式 | 用途 |
|------|---------|--------|------|
| lerobot | >= 0.4.0 | `pip install lerobot` 或 `pip install "lerobot[smolvla]"` | 数据集格式、record_loop、Robot 基类 |
| pyserial | >= 3.5 | `pip install pyserial` | 串口通信 |
| opencv-python | >= 4.5 | `pip install opencv-python` | 摄像头读取 |
| numpy | >= 1.21 | 自动依赖（lerobot 包含） | 数据处理 |
| evdev | >= 1.3 | `pip install evdev` | 键盘监听（直读 /dev/input/event*） |
| PyYAML | >= 6.0 | `pip install PyYAML` | 配置文件读取 |

> **推荐安装命令**：
> ```bash
> python -m pip install lerobot pyserial opencv-python evdev PyYAML
> ```
> 或一次性安装：`python -m pip install -r requirements.txt`
