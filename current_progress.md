1→# 当前进度
2→- 已完成 Sprint 0 的任务 1：输出架构模块与接口基线清单
3→- 已完成 Sprint 0 的任务 2：评估现有源码与基线差异并给出迁移策略
4→- 已完成 Sprint 0 的任务 3：确定缺失包与节点清单
5→- 已同步设计文档话题名称到现有代码
6→- 已注释 apriltag 相关启动代码
7→- 已完成 Sprint 0：替换 ugv_vision 命名为 camera
8→- 已评估 EKF 与 IMU 参数文件必要性：当前未接入启动链路，暂保留，待 Sprint 1 底盘融合时决定是否启用
9→- 已完成 Sprint 1：底盘串口数据流映射为 /odom/odom_raw 与 /imu/data_raw
10→- 已实现 Sprint 1：e_stop 急停机制（人为触发链路 TBD，待 VLA 完成后明确）
11→- 已完成 Sprint 1：底盘单元测试与接口验证脚本（测试执行移至 Sprint 5）
12→- 已完成 Sprint 2（重实现）：创建 camera/camera_node.py，通过 cv2.VideoCapture 自动检测 USB 摄像头（/dev/video0→-1→0），BestEffort QoS，发布 sensor_msgs/Image 到 /camera/image_raw；简化 launch 移除 image_proc 外部依赖；更新 package.xml（添加 cv_bridge）
14→- 已完成 Sprint 4：VLA 模块架构设计与基础代码实现（vla_bridge_node, ros_io, shared_buffer, smol_vla_policy_wrapper）
15→15→- 已完成 Sprint 5：建立 smol_bringup 启动包与系统参数分层
16→16→- 已完成 Sprint 5：建立系统级启动顺序与降级策略验证
- 已同步项目文档与默认配置：底盘串口切换为 CH341 USB 转串口 `/dev/ttyCH341USB0`
- 已优化 tools/ugv_data_collector 稳定性：增强 YAML 配置容错、修复断连时命令队列潜在阻塞、补强键盘速度档位线程安全与参数校验
- 已将 ugv_data_collector 键盘控制链路切换为 ugv_ctrl_tester 已验证的 evdev 方案（支持 Jetson 直连键盘/无桌面场景），并新增 --keyboard_device 参数
- 已将 ugv_data_collector 控制状态机对齐为与 ugv_ctrl_tester 零差异（同 evdev 按键处理、同速度向量更新、移除 Enter 提前结束逻辑）
- 已完成 ugv_data_collector 收尾清理：移除控制链路残留兼容参数与 Enter 文案，确保文档与运行行为一致
- 已完成 Sprint 5.5 升级：keyboard 包升级为 debug，keyboard_node 升级为 debug_node，新增订阅 /camera/image_raw、OSD 叠加、内置 MJPEG HTTP 服务（http://<robot-ip>:8080/），更新所有相关文档与 launch 配置
- 已明确 e_stop 人为触发链路：由 keyboard_node 发布 /e_stop，chassis 内置仲裁订阅响应
- 已修复 VLA 推理 OOM：将 PYTORCH_NO_CUDA_MEMORY_CACHING=1 提升到 smol_vla_policy.py 模块级（import torch 之前），确保首次 CUDA 分配即使用 raw cudaMalloc，规避 Jetson nvmap CMA 连续内存限制
- 已完成 VLA 独立推理验证：20 步测试平均 11ms/步，Git milestone 提交 ccf6d24，分支 milestone/smolvla-first-working
- 已完成 VLA ROS 节点端到端调试：相机 25Hz、odom/imu 20Hz 确认，VLA 推理 22-26ms/步稳定运行
- 已修复图像管道（ros_io.py）：bypass cv_bridge（Boost.Python 版本冲突），改用 np.frombuffer()+msg.step 处理 row padding，BGR→RGB flip，HWC→CHW transpose；外来编码（yuv/bayer）才回 fallback cv_bridge
- 已整合底盘 cmd_vel 转发：架构决策——ugv_driver 不启动（与 ugv_bringup 共享串口会冲突），cmd_vel 转发逻辑统一集成到 ugv_bringup.py；发送 JSON {"T":13,"X":vx,"Z":wz}
- 已实现 e_stop 可靠急停：ugv_bringup 订阅 /e_stop Bool，50ms watchdog 持续发零速，_cmd_vel_callback 在 e_stop_active 时立即返回；VLA 节点不感知 e_stop，chassis 节点为唯一仲裁门
- 已端到端验证：VLA 控制小车运动，空格键急停可靠生效
- 已完成 ugv_data_collector 二次检查与全面优化（含文档同步）：
  - 新增 evdev_teleop.py 急停帧过滤：Space 键设 is_estop_active 标志，record.py 跳过急停帧写入数据集，重按 WASD 自动恢复
  - 优化摄像头帧积压：connect() 设置 CAP_PROP_BUFFERSIZE=1，get_observation() 改用 grab()+retrieve() 保证读取最新帧
  - 修复 OSD 预览扩展：_preview_frame 新增 is_estop/cmd_vx/cmd_wz/obs_vx/obs_wz 参数，浏览器画面显示急停状态（红色 [E-STOP]）与双行速度信息（CMD/OBS）
  - 修复遗留 PNG 帧导致视频编码崩溃：每次 episode 开始前调用 _cleanup_stale_images 清理残留临时文件
  - 修复 LeRobot validate_frame 拒绝 timestamp 键：撤除传真实 timestamp 的改动（当前版本不支持）
  - 修正 DESIGN.md 与 README.md 文档：odl/odr 由"增量"纠正为"累积值"；image_key 从 laptop 更新到 camera1；部署时 preprocess.py 需改的 4 处完整说明；Space 急停过滤行为；--num_episodes 追加语义
- 已完成 Sprint 6：执行底盘单元测试与接口验证
- 已完成 Sprint 6：执行视觉发布的单元测试与接口验证
- 已完成 Sprint 6：执行 VLA 推理接口测试
- 已完成 Sprint 6：验证 e_stop watchdog（/e_stop true 后底盘持续发零速，50ms 间隔）
- 已回顾并统一环境文档：README 新增“Conda 环境约定”，明确默认 launch 为系统 Python；VLA 独立依赖推荐 conda `lerobot2`；tools/ugv_data_collector README 同步环境建议为 `lerobot2`
- 已补充 README 单节点调试说明：新增 VLA 推理节点运行方式（系统 Python `ros2 run vla vla_bridge_node` 与 conda `lerobot2` wrapper 启动）
- 已修复 vla_bridge_node_wrapper.sh：移除错误的 env/bin/activate 依赖，改为自动解析 conda base 并直接使用 env 内 python3；README 单节点调试已整理为最小可运行链路
- 已增强 vla_bridge_node_wrapper.sh：自动设置 LEROBOT_SRC 指向项目 ref_code，避免启动时误报 install 路径下 LeRobot source 缺失
- 已优化主启动：smol_bringup.launch.py 中 VLA 改为默认使用 conda `lerobot2` Python（支持参数 `vla_python:=...` 覆盖）；README“启动完整系统”已同步一句话启动说明
- 已增强主启动环境参数：新增 `lerobot_src`（默认指向项目 ref_code）并注入 VLA 进程环境，README 同步覆盖方式与硬件未接入时的告警说明
- 已修复主启动回归：VLA 启动环境改用 additional_env 追加 `LEROBOT_SRC`，避免覆盖 ROS 变量导致 conda Python 下 `rclpy` 导入失败
- 已修正主启动 `lerobot_src` 默认路径计算（定位到 smol_rugv/ref_code），避免默认回退到上级目录导致的 LeRobot source warning
- 已补充 README 一键启动变体：新增“全功能”和“无麦克风场景（enable_speech:=false）”命令
- 已接入“可选内存整理”启动链路：
  - wrapper 支持 `MEM_DEFRAG_ON_START=1` 启动前执行 `defrag_memory.sh`
  - 主启动支持 `enable_mem_defrag:=true` 与 `mem_defrag_script:=...` 参数
  - defrag_memory.sh 支持非交互 sudo 检查（无权限时自动跳过，不阻塞启动）
- 已新增 `vla_bridge_node_wrapper_checkpoint.sh`，并将 README 的 4.1 更新为 conda 环境下按 checkpoint 路径启动的命令
</toolcall_result>
