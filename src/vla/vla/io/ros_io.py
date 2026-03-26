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
        
        self.node.get_logger().info("ROSIO initialized with subscribers and publishers.")

    def _image_callback(self, msg: Image):
        try:
            # Convert to RGB (SmolVLA expects RGB)
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='rgb8')
            # ROS Time to float seconds
            timestamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            self.buffer.update("image", cv_image, timestamp)
        except Exception as e:
            self.node.get_logger().error(f"Image conversion failed: {e}")

    def _odom_callback(self, msg: Odometry):
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
