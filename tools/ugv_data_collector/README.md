# UGV Data Collector

基于 LeRobot 框架，为 UGV Rover 小车（Waveshare Jetson Orin 版）采集示范数据集的独立工具。

**不依赖 ROS2**，可直接运行在 Jetson 上。支持**键盘**遥控。

详细设计说明见 [DESIGN.md](DESIGN.md)。

---

## 快速开始

### 1. 安装依赖

```bash
cd tools/ugv_data_collector
pip install -r requirements.txt
```

### 2. 确认 lerobot 路径可用

本工具通过相对路径引用 `ref_code/lerobot-main (SmolVLA)/src`，确保目录结构完整：
```
smol_rugv/
├── ref_code/
│   └── lerobot-main (SmolVLA)/src/lerobot/  ← 必须存在
└── tools/ugv_data_collector/
```

### 3. 修改配置

编辑 `config/ugv_config.yaml`，至少修改：
- `serial.port`：确认串口设备路径
- `serial.wheel_base`：填入实际测量的轮距（米）
- `dataset.repo_id`：替换为你的 HuggingFace 用户名

### 4. 开始采集

```bash
# 键盘遥控
python record.py

# 使用命令行参数覆盖配置（优先级高于 yaml）
python record.py \
  --serial_port /dev/ttyCH341USB0 \
  --camera_index 0 \
  --repo_id myname/ugv-follow-task \
  --single_task "Follow the person" \
  --num_episodes 20 \
  --episode_time_s 30

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
| `Enter` | 结束当前 Episode，进入下一个 |
| `Esc` / `Ctrl+C` | 保存并退出 |

---

## 数据集结构

采集完成后，数据集保存在 `--output_dir`（默认 `./datasets/`）：

```
datasets/
└── myname/
    └── ugv-follow-task/
        ├── data/
        │   └── train/
        │       └── episode_000000.parquet  # 观测 + 动作的标量数据
        ├── videos/
        │   └── observation.images.camera_episode_000000.mp4
        └── meta/
            └── info.json
```

---

## 采集完成后的训练与部署

1. **训练**（在配置较好的 PC / 服务器上）：
   ```bash
   cd ref_code/lerobot-main\ \(SmolVLA\)
   lerobot-train \
     --policy.type=smolvla \
     --dataset.repo_id=myname/ugv-follow-task \
     --output_dir=./outputs/smolvla_ugv
   ```

2. **部署**：修改主工程 `src/vla/vla/inference/preprocess.py`：
   ```python
   # 将此行
   self.image_key = "observation.images.laptop"
   # 改为
   self.image_key = "observation.images.camera"
   ```
   并在 `src/smol_bringup/config/model.yaml` 中设置模型路径。
