import time as _time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from sensor_msgs.msg import Image, Imu
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
from std_msgs.msg import String
from cv_bridge import CvBridge
import numpy as np
from typing import Any

class ROSIO:
    """
    Handles ROS 2 communication: Subscribing to sensors and publishing commands.
    Converts ROS messages to Python/Numpy objects for the shared buffer.
    """
    def __init__(self, node: Node, buffer: Any):
        self.node = node
        self.buffer = buffer
        self.bridge = CvBridge()
        
        # QoS profiles based on design doc
        
        # Sensor data: BestEffort, Volatile (High frequency, drop old)
        sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )
        
        # Control & Instruction: Reliable (Must arrive)
        reliable_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE, 
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )

        # Subscribers
        self.sub_image = node.create_subscription(
            Image, 
            '/camera/image_raw', 
            self._image_callback, 
            sensor_qos
        )
            
        self.sub_odom = node.create_subscription(
            Odometry, 
            '/odom/odom_raw', 
            self._odom_callback, 
            sensor_qos
        )
            
        self.sub_imu = node.create_subscription(
            Imu, 
            '/imu/data_raw', 
            self._imu_callback, 
            sensor_qos
        )
            
        self.sub_instruction = node.create_subscription(
            String, 
            '/instruction_text', 
            self._instruction_callback, 
            reliable_qos
        )
            
        # Publisher
        self.pub_cmd_vel = node.create_publisher(
            Twist, 
            '/cmd_vel', 
            reliable_qos
        )
        
        # Frame-rate counters (written from ROS callbacks, read from status timer — same thread)
        self._cb_counts  = {"image": 0, "odom": 0, "imu": 0, "instruction": 0}
        self._hz_t0      = _time.monotonic()
        self._hz_counts0 = {"image": 0, "odom": 0, "imu": 0, "instruction": 0}

        self.node.get_logger().info("ROSIO initialized with subscribers and publishers.")

    def _image_callback(self, msg: Image):
        self._cb_counts["image"] += 1
        try:
            enc = msg.encoding.lower()
            h, w = msg.height, msg.width

            if enc in ('bgr8', 'rgb8', 'mono8'):
                # Direct numpy decode — bypasses cv_bridge Boost.Python version issues.
                # Equivalent to cv_bridge for packed formats; handles row-padding via msg.step.
                channels = 1 if enc == 'mono8' else 3
                raw = np.frombuffer(msg.data, dtype=np.uint8)
                if msg.step == w * channels:
                    frame = raw.reshape(h, w, channels)
                else:
                    # Row-padded: read full stride, then slice to actual width
                    frame = raw.reshape(h, msg.step)[:, : w * channels].reshape(h, w, channels)
                if enc == 'bgr8':
                    # BGR→RGB in-place view then copy
                    frame = frame[:, :, ::-1].copy()
                elif enc == 'mono8':
                    frame = np.stack([frame[:, :, 0]] * 3, axis=2)
                # else rgb8: already correct order
            else:
                # Fallback: try cv_bridge for exotic encodings (yuv, bayer, etc.)
                import cv2
                frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
                frame = frame[:, :, ::-1].copy()  # BGR→RGB

            if frame is None or frame.size == 0:
                self.node.get_logger().warn(
                    "Empty image received, skipping.", throttle_duration_sec=2.0)
                return

            # HWC (H, W, 3) → CHW (3, H, W) as expected by the LeRobot/SmolVLA pipeline.
            frame = frame.transpose(2, 0, 1)
            frame = np.ascontiguousarray(frame)
            timestamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            self.buffer.update("image", frame, timestamp)
        except Exception as e:
            self.node.get_logger().error(
                f"Image conversion failed: {e}", throttle_duration_sec=2.0)

    def _odom_callback(self, msg: Odometry):
        self._cb_counts["odom"] += 1
        try:
            # Store odom data as a dict of numpy arrays
            state = {
                "position": np.array([msg.pose.pose.position.x, msg.pose.pose.position.y, msg.pose.pose.position.z]),
                "orientation": np.array([
                    msg.pose.pose.orientation.x, 
                    msg.pose.pose.orientation.y, 
                    msg.pose.pose.orientation.z, 
                    msg.pose.pose.orientation.w
                ]),
                "linear_velocity": np.array([msg.twist.twist.linear.x, msg.twist.twist.linear.y, msg.twist.twist.linear.z]),
                "angular_velocity": np.array([msg.twist.twist.angular.x, msg.twist.twist.angular.y, msg.twist.twist.angular.z])
            }
            timestamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            self.buffer.update("odom", state, timestamp)
        except (AttributeError, ValueError, TypeError) as e:
            self.node.get_logger().error(f"Odom parsing failed: {e}", throttle_duration_sec=1.0)

    def _imu_callback(self, msg: Imu):
        self._cb_counts["imu"] += 1
        try:
            data = {
                "orientation": np.array([
                    msg.orientation.x, 
                    msg.orientation.y, 
                    msg.orientation.z, 
                    msg.orientation.w
                ]),
                "angular_velocity": np.array([msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z]),
                "linear_acceleration": np.array([msg.linear_acceleration.x, msg.linear_acceleration.y, msg.linear_acceleration.z])
            }
            timestamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            self.buffer.update("imu", data, timestamp)
        except (AttributeError, ValueError, TypeError) as e:
            self.node.get_logger().error(f"IMU parsing failed: {e}", throttle_duration_sec=1.0)

    def _instruction_callback(self, msg: String):
        self._cb_counts["instruction"] += 1
        try:
            # Use current system time as instructions don't always have header
            timestamp = self.node.get_clock().now().nanoseconds * 1e-9
            if not isinstance(msg.data, str) or not msg.data.strip():
                self.node.get_logger().debug("Received empty or invalid instruction, skipping.")
                return
            self.buffer.update("instruction", msg.data, timestamp)
            self.node.get_logger().info(f"Received instruction: {msg.data}")
        except (AttributeError, ValueError, TypeError) as e:
            self.node.get_logger().error(f"Instruction parsing failed: {e}", throttle_duration_sec=1.0)

    def publish_cmd_vel(self, linear: float, angular: float):
        msg = Twist()
        msg.linear.x = float(linear)
        msg.angular.z = float(angular)
        self.pub_cmd_vel.publish(msg)

    def get_topic_hz(self) -> dict:
        """Return rolling Hz since last call for each subscribed topic."""
        now = _time.monotonic()
        dt = now - self._hz_t0
        if dt < 0.01:
            return {k: 0.0 for k in self._cb_counts}
        hz = {k: (self._cb_counts[k] - self._hz_counts0[k]) / dt
              for k in self._cb_counts}
        self._hz_t0      = now
        self._hz_counts0 = dict(self._cb_counts)
        return hz
