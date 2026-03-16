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
</toolcall_result>
