# UGV Data Collector

基于 LeRobot 框架，为 UGV Rover 小车（Waveshare Jetson Orin 版）采集示范数据集的独立工具。

键盘控制复用 `ugv_ctrl_tester` 已验证方案：默认使用 Linux `evdev` 直读 `/dev/input/event*`，适配 Jetson 直连键盘、SSH 和 VS Code 终端场景。

**不依赖 ROS2**，可直接运行在 Jetson 上。支持**键盘**遥控。

详细设计说明见 [DESIGN.md](DESIGN.md)。

---

## 快速开始

### 1. 确保 LeRobot 已安装

本工具基于 LeRobot 框架。若尚未安装，运行以下命令：

```bash
# 推荐：使用 python -m pip 确保安装到当前 Python 环境
python -m pip install lerobot

# 若需要完整的 SmolVLA 训练功能，可安装扩展包
python -m pip install "lerobot[smolvla]"
```

> **环境提示**：若使用 conda 环境，先激活对应环境（如 `conda activate lerobot`），再运行上述命令。

### 2. 安装本工具依赖

```bash
cd tools/ugv_data_collector
python -m pip install -r requirements.txt
```

> 若 requirements.txt 中已包含 `lerobot`，可直接运行。否则上一步已自动包含。

### 3. 修改配置

编辑 `config/ugv_config.yaml`，至少修改：
- `serial.port`：确认串口设备路径
- `serial.wheel_base`：填入实际测量的轮距（米）
- `dataset.repo_id`：替换为你的 HuggingFace 用户名

### 4. 开始采集

```bash
# 默认：手动 Enter 控制每个 episode（推荐）
python record.py

# 自动定时模式（episode_time_s 到时自动结束）
python record.py --auto

# 使用命令行参数覆盖配置
python record.py \
  --serial_port /dev/ttyCH341USB0 \
  --camera_index 0 \
  --keyboard_device /dev/input/event3 \
  --repo_id myname/ugv-follow-task \
  --single_task "Follow the person" \
  --num_episodes 20 \
  --episode_time_s 30

# 关闭摄像头预览（默认开启，访问 http://<机器人IP>:8080/stream 查看）
python record.py --no-preview

# 测试模式（跳过真实串口和摄像头，验证流程）
python record.py --dry_run
```

---

## 遥控操作说明

### 键盘操作

| 按键 | 动作 |
|------|------|
| `W` | 前进 |
| `S` | 后退 |
| `A` | 左转 |
| `D` | 右转 |
| `Q` | 提高速度档 |
| `E` | 降低速度档 |
| `Space` | 急停 |
| `Enter` | 开始录制 / 结束当前 episode（手动模式） |
| `Esc` / `Ctrl+C` | 保存并退出 |

> 键盘设备默认自动发现；如有多设备，使用 `--keyboard_device /dev/input/eventN` 明确指定。

---

## 摄像头预览

录制时默认开启 MJPEG HTTP 预览流，在同局域网的浏览器打开：

```
http://<机器人IP>:8080/stream
```

启动后终端会打印完整地址。使用 `--no-preview` 关闭。

---

## 数据集结构

采集完成后，数据集保存在 `--output_dir`（默认 `./datasets/`）：

```
datasets/
└── myname/
    └── ugv-follow-task/
        ├── data/
        │   └── chunk-000/
        │       ├── file-000.parquet   # 每个 episode：observation.state + action + 元数据
        │       └── file-001.parquet
        ├── videos/
        │   └── observation.images.camera/
        │       └── chunk-000/
        │           ├── file-000.mp4   # 每个 episode 的相机帧（AV1 压缩）
        │           └── file-001.mp4
        └── meta/
            ├── info.json              # 数据集配置（fps、features、路径模板）
            ├── stats.json             # 各特征统计量（均值/标准差）
            ├── tasks.parquet          # task_index → 任务描述映射
            └── episodes/              # 每个 episode 的摘要信息
```

---

## 采集完成后的训练与部署

### 训练（在配置较好的 PC / 服务器上）

若已安装 `lerobot[smolvla]`，可直接运行：

```bash
# 方式 1：直接使用 lerobot-train 命令
lerobot-train \
  policy.type=smolvla \
  dataset.repo_id=myname/ugv-follow-task \
  output_dir=./outputs/smolvla_ugv

# 方式 2：若上述命令不可用，使用 Python 模块调用
python -m lerobot.scripts.train \
  policy.type=smolvla \
  dataset.repo_id=myname/ugv-follow-task \
  output_dir=./outputs/smolvla_ugv
```

### 部署（回到主工程）

修改主工程的两个文件：

**1. `src/vla/vla/inference/preprocess.py`**
```python
# 将此行
self.image_key = "observation.images.laptop"
# 改为
self.image_key = "observation.images.camera"
```

**2. `src/smol_bringup/config/model.yaml`**
```yaml
# 设置本地或远程模型路径
model_id: "local:///path/to/smolvla_ugv"
# 或上传到 HuggingFace 后使用
# model_id: "myname/smolvla-ugv-policy"
```
