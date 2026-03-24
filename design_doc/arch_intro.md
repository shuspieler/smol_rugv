一、 ROS2 功能包（Package）划分
系统被划分为五个核心功能包，实现了感知、交互、驱动、智能决策与调试控制的分离：
camera/：负责视觉数据采集 。
speech/：负责语音交互 。
chassis/：负责底层底盘控制与传感器反馈 。
vla/：负责大模型桥接与推理决策 。
debug/：负责键盘调试控制与急停，以及摄像头画面 MJPEG 推流，直连底盘，绕过 VLA 推理链路 。

二、 各功能包详细职责与通信接口
1. Camera Package (视觉包)

主要任务：读取摄像头原始数据并将其转换为 ROS2 标准图像格式（Image）进行发布 。
设计原则：该节点保持轻量化，不包含感知、推理、同步或预处理逻辑 。
通信话题：
发布：/camera/image_raw (消息类型：sensor_msgs/Image) 。

2. Speech Package (语音包)

主要任务：将麦克风采集的音频输入实时转换为文本指令 。
通信话题：
发布：/instruction_text (消息类型：std_msgs/String) 。

3. Chassis Package (底盘包)

主要任务：通过串口与 ESP32 通信，实现底层协议解析、轮速及 IMU 数据解码，并将控制指令下发给电机 。
通信话题 ：
订阅：/cmd_vel (消息类型：geometry_msgs/Twist) 。
订阅：/e_stop (消息类型：std_msgs/Bool，由 debug_node 发布，用于紧急制动) 。
发布：/odom/odom_raw (消息类型：nav_msgs/Odometry) 。
发布：/imu/data_raw (消息类型：sensor_msgs/Imu) 。

4. Debug Package (调试包)

主要任务：提供底盘调试、急停与实时摄像头预览能力，完全绕过 VLA 推理链路。
设计原则：独立于 VLA，优先级高于 VLA 输出；所有功能均不依赖桌面/X11，适配 Jetson 无头/SSH 场景。
操作方式：
WASD 键：直接控制底盘移动（前/后/左/右）。
空格键：立即触发急停（发布 /e_stop true）；松开时解除（发布 /e_stop false）。
Q/E 键：调节速度档位。
Esc 键：优雅退出节点。
摄像头 MJPEG 流：订阅 /camera/image_raw，叠加 OSD（速度/档位/e-stop 状态），通过内置 HTTP 服务推流，浏览器访问 http://<robot-ip>:8080/ 即可预览。
通信话题：
订阅：/camera/image_raw (消息类型：sensor_msgs/Image) 。
发布：/cmd_vel (消息类型：geometry_msgs/Twist，直接发给 chassis_driver_node) 。
发布：/e_stop (消息类型：std_msgs/Bool，急停信号) 。

5. VLA Package (决策桥接包)

主要任务：作为“大脑”，负责连接 ROS2 环境与 smolVLA / LeRobot 推理框架 。
节点设置：该包仅包含一个核心节点 vla_bridge_node 。
通信话题 ：
订阅：/camera/image_raw、/odom/odom_raw、/imu/data_raw 以及 /instruction_text 。
发布：/cmd_vel (发送至 chassis_driver_node) 。

三、 VLA 功能包工程结构

VLA 模块遵循清晰的代码组织架构，确保算法与 IO 逻辑分离：

vla/
├── vla_bridge_node.py      # 唯一的 ROS2 Node 入口 
├── io/
│   └── ros_io.py           # 处理订阅、发布及 Buffer 写入
├── core/
│   ├── shared_buffer.py    # 线程间共享数据缓冲区
│   └── sync_policy.py      # 数据同步策略 
├── inference/
│   ├── vla_loop.py         # 独立于 ROS 的模型推理线程 
│   └── preprocess.py       # 多模态数据预处理 
├── model/
│   └── smol_vla_policy.py  # 封装 LeRobot / SmolVLA 模型
