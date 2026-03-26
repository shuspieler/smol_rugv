## Sprint 0
- [done] 评估 EKF 与 IMU 参数文件的必要性（暂不启用 EKF，保留参数文件备用）

## Sprint 1
- [done] 实现 e_stop 急停仲裁：订阅 /e_stop Bool，50ms watchdog 持续发零速
- [done] 梳理底盘串口数据流，映射到 /odom/odom_raw 与 /imu/data_raw
- [done] 设计底盘单元测试与接口验证脚本（测试执行移至 Sprint 6）

## Sprint 5 / Hardening（2026-03-24）
- [done] 移除 is_jetson() 平台检测（os.walk 遍历全盘），硬编码 /dev/ttyCH341USB0
- [done] 修复 ugv_driver voltage_callback 硬编码旧路径（改为 ROS logger warn）
- [done] 修复 ugv_bringup 里程计首帧问题：首帧以当前 odl/odr 为基准，跳过差分计算
- [done] 新增里程计跳变保护：|vx| >= 5 m/s 丢弃（ESP32 重启/溢出异常帧）
- [done] 新增角速度跳变保护：|wz| >= 20 rad/s 丢弃

## Sprint 5 / Observability（2026-03-24）
- [done] ugv_driver：新增串口打开确认、节点就绪、cmd_vel（INFO throttle 1s）、E-Stop 状态变更、电压（INFO throttle 10s）日志
- [done] ugv_driver：新增串口 TX payload DEBUG 日志（--log-level DEBUG 可查看原始 JSON）
- [done] ugv_bringup：新增串口打开确认、节点就绪 INFO 日志
- [done] ugv_bringup：修复 feedback_loop 静默丢帧问题（feedback_data 返回 None 时改为 WARN 并提前 return）
- [done] ugv_bringup：修复 BaseController 使用 stdlib logging 导致报错不出现在 ros2 终端的问题，改为 ROS logger WARN（throttle 5s）
- [done] ugv_bringup：新增里程计周期状态 INFO 日志（vx/wz/x/y/yaw，throttle 5s）
- [done] ugv_bringup：新增电压周期 INFO 日志（throttle 10s）

## Sprint 6（待执行）
- [ ] 上机验证 ugv_bringup：ros2 topic echo /odom/odom_raw，确认里程计正常累积
- [ ] 上机验证 ugv_driver：ros2 topic pub /cmd_vel，确认底盘响应
- [x] 验证 e_stop watchdog：发布 /e_stop true 后底盘持续发零速（50ms 间隔）——已通过空格键实测
- [ ] 验证 wheel_base 参数配置后 /odom/odom_raw 的 angular.z 是否正确
- [ ] 压力测试：长时运行里程计累积是否有漂移
- [ ] 用 --log-level DEBUG 启动 ugv_driver，确认 serial TX JSON 打印正常

## Sprint 5.6 / cmd_vel + e_stop 整合（2026-XX-XX）
- [done] 废弃 ugv_driver 独立运行（与 ugv_bringup 共享 /dev/ttyCH341USB0 会冲突）
- [done] 在 ugv_bringup 新增 /cmd_vel 订阅 → _cmd_vel_callback → base_controller.send_command({"T":13,"X":vx,"Z":wz})
- [done] 新增最小角速度门限保护：|wz| 在 (0, 0.2) 时钳制为 ±0.2 防止死区
- [done] 新增 /e_stop Bool 订阅 → _e_stop_callback 设置 e_stop_active flag
- [done] 新增 50ms watchdog timer → _e_stop_watchdog：e_stop 激活期间持续发零速到串口
- [done] _cmd_vel_callback 在 e_stop_active=True 时立即 return，拒绝 VLA 速度指令
- [done] 端到端验证：VLA 40Hz 推理期间空格键急停可靠生效
