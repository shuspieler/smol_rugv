# smol_rugv

基于 Jetson Orin Nano 的 UGV 智能小车项目，将 [SmolVLA](https://huggingface.co/lerobot/smolvla_base)
模型部署到移动机器人上，通过摄像头图像与语音指令实现端到端自动控制。

## 功能目标

- **视觉跟随**：摄像头采集图像，VLA 模型实时推理，驱动底盘跟随人或物体
- **语音控制**：麦克风采集语音，转换为文字指令后送入 VLA 决策链路

## 硬件平台

| 组件 | 型号 |
|------|------|
| 计算平台 | NVIDIA Jetson Orin Nano |
| 底盘 | Waveshare UGV Rover（ESP32 串口控制，四轮驱动） |
| 摄像头 | 单 USB 摄像头 |

参考：[Waveshare UGV Rover Jetson Orin ROS2 Wiki](https://www.waveshare.net/wiki/UGV_Rover_Jetson_Orin_ROS2)

> ESP32 底盘固件复用 Waveshare 原厂实现，本项目不涉及固件开发。

## 系统架构

系统由五个 ROS2 功能包 + 1 调试包组成，以异步话题通信解耦感知、语言、决策与执行：

```
键盘 ───► debug_node ──┬──► /cmd_vel ──────────────────────────────────────►┐
                       └──► /e_stop                                          │
摄像头 ─► camera_node ──────► /camera/image_raw ──► vla_bridge_node ─► /cmd_vel ─►├──► ugv_driver ◄──► 底盘串口
麦克风 ─► speech_node ──────► /instruction_text ──► vla_bridge_node          │         │
                                                                              │    ugv_bringup ◄── 底盘串口
debug_node ◄── /camera/image_raw, /odom/odom_raw (OSD 速度显示)              │         ├──► /odom/odom_raw
  MJPEG 预览 http://IP:8080                                                  │         └──► /imu/data_raw
```

| 包 | 节点 | 职责 |
|----|------|------|
| `camera` | `camera_node` | 发布 `/camera/image_raw`（25fps，轻量，不含推理） |
| `speech` | `speech_node` | 语音转文字，发布 `/instruction_text` |
| `chassis` | `ugv_driver` + `ugv_bringup` | 串口驱动底盘；解析里程计与 IMU；订阅 `/cmd_vel` 与 `/e_stop` |
| `vla` | `vla_bridge_node` | SmolVLA 推理桥接：多路输入 → `/cmd_vel`，双线程架构 |
| `debug` | `debug_node` | 键盘遥控（WASD/QE/Space）+ MJPEG 调试预览 + E-Stop 发布 |
| `smol_bringup` | — | 系统级启动包，协调所有节点启动与参数分发 |

详细架构与接口规范见 [design_doc/](design_doc/)。

## 目录结构

```
smol_rugv/
├── src/                        # ROS2 功能包源码
│   ├── camera/                 # 视觉采集节点（camera_node）
│   ├── debug/                  # 键盘遥控 + MJPEG 调试节点（debug_node）
│   ├── speech/                 # 语音识别节点（speech_node）
│   ├── chassis/                # 底盘串口驱动节点（ugv_driver + ugv_bringup）
│   ├── vla/                    # VLA 决策桥接节点（vla_bridge_node）
│   └── smol_bringup/           # 系统级启动包（参数分发 + 条件启动）
├── tools/
│   ├── ugv_ctrl_tester/        # 零依赖控制通路验证工具（WASD + 图样采样）
│   ├── ugv_data_collector/     # LeRobot 兼容数据采集工具
│   ├── offical_example/        # 厂商参考示例
│   └── serial_raw.sh           # 串口原始数据查看脚本
├── ref_code/                   # 外部依赖（LeRobot SmolVLA 源码引用）
├── design_doc/                 # 架构设计文档
└── .vscode/mcp.json            # Copilot Agent MCP 配置
```

## 快速开始

### 环境依赖

```bash
# ROS2 Humble（Ubuntu 22.04 / JetPack）
# Python 3.10+

# 安装控制验证工具依赖
pip install -r tools/ugv_ctrl_tester/requirements.txt
```

### Conda 环境约定（重要）

- 主系统默认启动（`ros2 launch smol_bringup smol_bringup.launch.py`）中的 `vla_bridge_node` 由 conda `lerobot2` Python 拉起（默认 `/home/jetson/miniforge3/envs/lerobot2/bin/python3`）。
- 若需要 VLA 使用独立 Conda 依赖（`torch`、`transformers`、`lerobot`），请使用 `lerobot2` 环境，并通过 `src/vla/bin/vla_bridge_node_wrapper.sh` 或 `src/smol_bringup/launch/smol_bringup_conda.launch.py.example` 的方式启动。
- 建议统一约定：VLA 与数据采集工具都使用同一个 Conda 环境 `lerobot2`，避免版本不一致。

示例：

```bash
conda activate lerobot2
python -V
which python
```

### 验证控制通路（无需 LeRobot）

在接真实硬件前，先用 `ugv_ctrl_tester` 确认串口和摄像头正常：

```bash
# 干跑模式（虚拟底盘和相机，无需接硬件）
python tools/ugv_ctrl_tester/ctrl_test.py --dry_run

# 真实硬件
python tools/ugv_ctrl_tester/ctrl_test.py --serial_port /dev/ttyCH341USB0 --camera_index 0
```

键盘操作：`WASD` 移动，`QE` 调速，`Space` 急停，`Esc` 退出。

### 启动完整系统

```bash
# 构建
colcon build --symlink-install

# 启动
source install/setup.bash
ros2 launch smol_bringup smol_bringup.launch.py
```

常用一键启动：
- 全功能：ros2 launch smol_bringup smol_bringup.launch.py
- 无麦克风场景：ros2 launch smol_bringup smol_bringup.launch.py enable_speech:=false
- 启动前执行一次内存整理（可选）：ros2 launch smol_bringup smol_bringup.launch.py enable_mem_defrag:=true
- 无麦克风 + 内存整理（可选）：ros2 launch smol_bringup smol_bringup.launch.py enable_speech:=false enable_mem_defrag:=true

说明：
- 上述一条 `ros2 launch` 会启动 camera/chassis/speech/vla 等相关节点，其中 VLA 默认使用 conda `lerobot2` 的 Python（`/home/jetson/miniforge3/envs/lerobot2/bin/python3`）。
- 若你的环境路径不同，可覆盖：`ros2 launch smol_bringup smol_bringup.launch.py vla_python:=/path/to/your/env/bin/python3`
- 若 LeRobot 源码路径不同，可覆盖：`ros2 launch smol_bringup smol_bringup.launch.py lerobot_src:=/path/to/lerobot/src`
- 若内存整理脚本路径不同，可覆盖：`ros2 launch smol_bringup smol_bringup.launch.py enable_mem_defrag:=true mem_defrag_script:=/path/to/defrag_memory.sh`
- 若麦克风/摄像头未接入，`speech_node`/`camera_node` 可能打印设备告警，但不影响底盘与 VLA 节点进程拉起。
- 内存整理依赖 root 或 sudo NOPASSWD；若权限不足会打印警告并自动跳过，不阻塞启动。

### 单节点开发调试

```bash
source install/setup.bash

# 1) 最小可运行链路（先开这两个终端）
ros2 run camera camera_node        # 发布 /camera/image_raw
ros2 run chassis ugv_bringup       # 底盘读写 + 发布 odom/imu + 接收 /cmd_vel

# 2) VLA 推理节点（推荐：Conda lerobot2 环境，第三个终端）
bash src/vla/bin/vla_bridge_node_wrapper.sh

# 2.1) VLA 启动前执行内存整理（可选）
MEM_DEFRAG_ON_START=1 bash src/vla/bin/vla_bridge_node_wrapper.sh

# 3) 可选调试节点（第四个终端）
ros2 run debug debug_node          # 键盘遥控 + MJPEG(http://IP:8080)

# 4) 仅在需要系统 Python 路径排障时使用
ros2 run vla vla_bridge_node

# 5) 查看底盘详细日志（可选）
ros2 run chassis ugv_bringup --ros-args --log-level DEBUG
```

说明：
- 启动前请先执行 `source install/setup.bash`，确保 `vla` 包可被 Python 找到。
- 若使用 `ros2 run vla vla_bridge_node`，请确认系统 Python 已安装 `torch` / `transformers` / `lerobot`。
- 若依赖安装在 conda `lerobot2`，优先使用 `vla_bridge_node_wrapper.sh` 启动，避免 Python 环境不一致导致导入失败。

## 开发进度

| Sprint | 内容 | 状态 |
|--------|------|------|
| Sprint 0 | 架构确认与基线整理 | ✅ 完成 |
| Sprint 1 | 底盘串口驱动与急停仲裁 | ✅ 完成 |
| Sprint 2 | 视觉采集节点（camera_node 实现，25fps 验证） | ✅ 完成 |
| Sprint 3 | 语音识别模块 | 🔲 待验证 |
| Sprint 4 | VLA 决策桥接实现 | 🔲 待模型训练 |
| Sprint 5 | 底盘加固 + 全节点可观测性 | ✅ 完成 |
| Sprint 6 | 系统硬件验证与端到端测试 | 🔲 进行中 |

**Sprint 5 完成内容：**
- 移除 `is_jetson()` 全盘扫描，硬编码 `/dev/ttyCH341USB0`
- 修复 `ugv_bringup` 里程计首帧跳变、添加 vx/wz 噪声剔除（5 m/s / 20 rad/s 阈值）
- `ugv_driver` 与 `ugv_bringup` 全节点 INFO/DEBUG 日志覆盖，`ros2 run` 终端可见完整状态
- `camera_node` 新增 `namespace="camera"`，`ros2 run` 直接启动 topic 路径正确为 `/camera/image_raw`；新增 2 秒重连冷却，防止读帧失败时高频重连锁死设备
- `debug_node` MJPEG 流 + OSD（指令速度/反馈速度/E-Stop），键盘可选（无设备不崩溃）
- USB 自动休眠永久禁用（udev rule + rc.local）

**待办：**
- VLA 模型训练（使用 LeRobot 采集数据后训练适配小车的权重）
- Sprint 6 硬件验证（odom hz、e_stop watchdog、wheel_base 校准）

## License

MIT