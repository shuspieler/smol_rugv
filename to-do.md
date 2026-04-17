# Sprint 0：架构确认与基线整理
- [x] 对照 design_doc 完成系统模块与接口基线清单
- [x] 评估 src 现有包与架构差异并输出迁移策略
- [x] 确定缺失包与节点清单（speech、vla、smol_bringup）
- [x] 检查并替换代码中的 ugv_vision 命名为 camera
- [x] 评估 EKF 与 IMU 参数文件的必要性

# Sprint 1：底盘与安全仲裁框架
- [x] 梳理底盘串口数据流并映射到 /odom/odom_raw 与 /imu/data_raw
- [x] 设计并实现 e_stop 急停仲裁（人为触发链路 TBD，待 VLA 完成后明确）
- [x] 设计底盘单元测试与接口验证

# Sprint 2：视觉采集与发布
- [x] 明确 camera_node 发布 /camera/image_raw 的实现路径
- [x] 对齐相机参数与 QoS 配置

# Sprint 3：语音模块
- [x] 定义 speech_node 输入与 /instruction_text 输出规范
- [x] 选型语音识别实现并完成最小可用版本

# Sprint 4：VLA 决策桥接与适配实现
- [x] 建立 vla 包结构与 vla_bridge_node
- [x] 实现同步策略与动作队列控制逻辑
- [x] 确认 SmolVLA 适配方案（使用 LeRobot 框架训练，调整输入输出维度）
- [x] 实施 VLA 适配代码修改（支持 2D 动作空间与自定义状态维度）
- [x] 验证 VLA Runtime 配置灵活性

# Sprint 5：系统级启动、集成准备与模型训练
- [x] 建立 smol_bringup 启动包与系统参数分层
- [x] 建立系统级启动顺序与降级策略验证
- [x] 明确 e_stop 人为触发链路：由 keyboard_node 直接发布 /e_stop
- [x] 执行 VLA 模型训练（外部 LeRobot 环境，输出适配小车的模型权重）

# Sprint 5.6：VLA ROS 节点集成与底盘驱动整合
- [x] 修复图像管道：bypass cv_bridge，numpy 直接解码，HWC→CHW，row-padding 处理
- [x] 修复 sync_policy：odom 缺失时返回零状态（不阻塞推理）
- [x] 整合底盘 cmd_vel 转发到 ugv_bringup（废弃 ugv_driver，避免串口冲突）
- [x] 实现 e_stop 可靠急停：ugv_bringup 50ms watchdog + _cmd_vel_callback 仲裁门
- [x] 端到端验证：VLA 控制小车运动，空格急停可靠（chassis 为唯一仲裁层）

# Sprint 5.5：调试模块（keyboard 升级为 debug）
- [x] 新建 debug 包（package.xml / setup.py / setup.cfg）
- [x] 实现 debug_node：evdev 直读键盘 + WASD 控制 + 空格急停
- [x] 订阅 /camera/image_raw，叠加 OSD 后通过内置 MJPEG HTTP 服务推流到浏览器
- [x] 注册到 smol_bringup.launch.py，enable_debug 开关默认 false

# Sprint 6：系统验证与测试
- [x] 执行底盘单元测试与接口验证（移自 Sprint 1）
- [x] 执行视觉发布的单元测试与接口验证（移自 Sprint 2）
- [ ] 执行语音指令处理单元测试（移自 Sprint 3）
- [x] 执行 VLA 推理接口测试（移自 Sprint 4）
- [x] 验证 e_stop watchdog：发布 /e_stop true 后底盘持续发零速（50ms 间隔）
- [ ] 压力测试：VLA 长时运行里程计累积、action queue 稳定性
- [ ] 设计与执行端到端集成测试

# Sprint 7：微调与强化学习
## 7.1 Fine-tuning（监督式微调）
- [x] 学习 LoRA / QLoRA 原理，理解为何适用于 VLA 边缘微调
- [x] 掌握 LeRobot 数据集格式（HuggingFace Dataset，episode/frame 结构）
- [x] 在 PC/外部机器上对 SmolVLA 执行 LoRA 微调，使用自采小车数据集
- [ ] 对比原始权重与微调权重在实机上的推理行为差异
- [x] 了解 PEFT（Parameter-Efficient Fine-Tuning）库与 LeRobot 的集成方式

## 7.2 强化学习（RL）
- [ ] 学习 RL 基础：MDP、reward、policy gradient、PPO、SAC 概念
- [ ] 了解 VLA + RL 的结合思路（RLHF、online RL on robot）
- [ ] 阅读 LeRobot RL 相关 PR/文档，了解当前支持状态
- [ ] 设计小车场景的简单 reward 函数（如：到达目标点、避障）
- [ ] 在仿真/离线环境中跑通基础 RL 实验（可选 IsaacSim/Gym wrapper）

## 7.3 量化（Quantization）
- [ ] 学习量化基础：PTQ（训练后量化）vs QAT（量化感知训练），INT8/FP16
- [ ] 掌握 PyTorch 原生量化工具（torch.quantization / torch.ao）
- [ ] 在 Jetson 上使用 FP16（torch.cuda.amp / model.half()）运行 SmolVLA，对比延迟
- [ ] 了解 NVIDIA TensorRT 量化流程（ONNX → TRT Engine，INT8 校准）
- [ ] 评估量化后模型推理精度损失与速度收益

## 7.4 TensorRT 与边缘端部署
- [ ] 学习 TensorRT 基础：Engine 构建、Layer Fusion、Dynamic Shape
- [ ] 将 SmolVLA 视觉编码器（SigLIP/DINOv2 backbone）导出为 ONNX
- [ ] 使用 trtexec 或 Python API 构建 TRT Engine 并在 Jetson 上 benchmark
- [ ] 学习 torch2trt / TensorRT-LLM 对 Transformer 模型的加速支持
- [ ] 探索 NVIDIA Jetson 专项优化：DLA（Deep Learning Accelerator）适配、统一内存策略
- [ ] 集成 TRT 推理引擎到 vla_bridge_node（替换原 PyTorch 推理路径）

## 7.5 综合部署验证
- [ ] 在 Jetson 上对比四种推理方案延迟：FP32 / FP16 / INT8-PTQ / TRT Engine
- [ ] 建立推理 benchmark 脚本（延迟、显存、CPU 占用、掉帧率）
- [ ] 验证量化/TRT 模型在实机上控制效果（与原模型对比）
- [ ] 更新 smol_bringup 配置，支持通过参数切换推理后端

