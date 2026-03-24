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

### 单节点开发调试

```bash
source install/setup.bash

# 摄像头（发布 /camera/image_raw）
ros2 run camera camera_node

# 底盘（两个节点均需启动）
ros2 run chassis ugv_bringup   # 读取串口反馈，发布 odom / IMU
ros2 run chassis ugv_driver    # 订阅 cmd_vel / e_stop，驱动 ESP32

# 调试预览（键盘遥控 + http://IP:8080 MJPEG 流）
ros2 run debug debug_node

# 查看完整串口 TX 日志（DEBUG 级别）
ros2 run chassis ugv_driver --ros-args --log-level DEBUG
```

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