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
12→- 已完成 Sprint 2：camera_node 对接 usb_cam，实现路径为 /camera/image_raw
13→- 已完成 Sprint 2：相机参数 frame_id 对齐及 QoS 配置
14→- 已完成 Sprint 4：VLA 模块架构设计与基础代码实现（vla_bridge_node, ros_io, shared_buffer, smol_vla_policy_wrapper）
15→15→- 已完成 Sprint 5：建立 smol_bringup 启动包与系统参数分层
16→16→- 已完成 Sprint 5：建立系统级启动顺序与降级策略验证
- 已同步项目文档与默认配置：底盘串口切换为 CH341 USB 转串口 `/dev/ttyCH341USB0`
- 已优化 tools/ugv_data_collector 稳定性：增强 YAML 配置容错、修复断连时命令队列潜在阻塞、补强键盘速度档位线程安全与参数校验
- 已将 ugv_data_collector 键盘控制链路切换为 ugv_ctrl_tester 已验证的 evdev 方案（支持 Jetson 直连键盘/无桌面场景），并新增 --keyboard_device 参数
- 已将 ugv_data_collector 控制状态机对齐为与 ugv_ctrl_tester 零差异（同 evdev 按键处理、同速度向量更新、移除 Enter 提前结束逻辑）
- 已完成 ugv_data_collector 收尾清理：移除控制链路残留兼容参数与 Enter 文案，确保文档与运行行为一致
</toolcall_result>
