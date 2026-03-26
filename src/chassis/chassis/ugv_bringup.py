import serial
import json
import queue
import threading
import rclpy
from rclpy.node import Node
import logging
import time
from std_msgs.msg import Header, Float32, Bool
from sensor_msgs.msg import Imu, MagneticField
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
import math

# Jetson Orin Nano: CH341 USB-serial adapter
_DEFAULT_SERIAL_PORT = '/dev/ttyCH341USB0'

# Helper class for reading lines from a serial port
class ReadLine:
    def __init__(self, s):
        self.buf = bytearray()  # Buffer to store incoming data
        self.s = s  # Serial object

    # Read a line of data from the serial input
    def readline(self):
        i = self.buf.find(b"\n")
        if i >= 0:
            r = self.buf[:i+1]
            self.buf = self.buf[i+1:]
            return r
        while True:
            i = max(1, min(512, self.s.in_waiting))  # Read from serial buffer
            data = self.s.read(i)
            i = data.find(b"\n")
            if i >= 0:
                r = self.buf + data[:i+1]
                self.buf[0:] = data[i+1:]
                return r
            else:
                self.buf.extend(data)

    # Clear the buffer
    def clear_buffer(self):
        self.s.reset_input_buffer()

# Base controller class for managing UART communication and processing commands
class BaseController:
    def __init__(self, uart_dev_set, baud_set):
        self.logger = logging.getLogger('BaseController')  # Logger setup
        self.ser = serial.Serial(uart_dev_set, baud_set, timeout=1)  # Open serial connection
        self.rl = ReadLine(self.ser)  # Initialize ReadLine helper
        self.command_queue = queue.Queue()  # Command queue for sending data
        self.command_thread = threading.Thread(target=self.process_commands, daemon=True)  # Start a separate thread for processing commands
        self.command_thread.start()
        self.data_buffer = None  # Buffer for holding received data
        # Base data structure to hold sensor values
        self.base_data = {"T": 1001, "L": 0, "R": 0, "ax": 0, "ay": 0, "az": 0, "gx": 0, "gy": 0, "gz": 0, "mx": 0, "my": 0, "mz": 0, "odl": 0, "odr": 0, "v": 0}
    
    # Function to read and return feedback data from the serial input
    def feedback_data(self):
        try:
            line = self.rl.readline().decode('utf-8')  # Read line from UART
            self.data_buffer = json.loads(line)  # Parse JSON data
            self.base_data = self.data_buffer  # Store received data
            return self.base_data  # Return base data
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e} with line: {line}")  # Log error
            self.rl.clear_buffer()  # Clear buffer on error
        except Exception as e:
            self.logger.error(f"[base_ctrl.feedback_data] unexpected error: {e}")
            self.rl.clear_buffer()

    # Receive and decode data from the serial connection
    def on_data_received(self):
        self.ser.reset_input_buffer()
        data_read = json.loads(self.rl.readline().decode('utf-8'))  # Read and parse JSON data
        return data_read

    # Add a command to the queue to be sent via UART
    def send_command(self, data):
        self.command_queue.put(data)

    # Thread function to process and send commands from the queue
    def process_commands(self):
        while True:
            data = self.command_queue.get()  # Get command from the queue
            self.ser.write((json.dumps(data) + '\n').encode("utf-8"))  # Send command as JSON over UART

    # Send control data as JSON via UART
    def base_json_ctrl(self, input_json):
        self.send_command(input_json)

class DummyBaseController:
    def __init__(self):
        self.base_data = {"T": 1001, "L": 0, "R": 0, "ax": 0, "ay": 0, "az": 0, "gx": 0, "gy": 0, "gz": 0, "mx": 0, "my": 0, "mz": 0, "odl": 0, "odr": 0, "v": 0}

    def feedback_data(self):
        return self.base_data

# ROS node class for bringing up the UGV system and publishing sensor data
class ugv_bringup(Node):
    def __init__(self, base_controller=None, test_mode=False):
        super().__init__('ugv_bringup')
        # Publishers for IMU data, magnetic field data, odometry, and voltage
        self.imu_data_raw_publisher_ = self.create_publisher(Imu, "imu/data_raw", 100)
        self.imu_mag_publisher_ = self.create_publisher(MagneticField, "imu/mag", 100)
        self.odom_publisher_ = self.create_publisher(Odometry, "odom/odom_raw", 100)
        self.voltage_publisher_ = self.create_publisher(Float32, "voltage", 50)
        # UGV Rover (mainType:02) TRACK_WIDTH = 0.172 m（源自 ugv_config.h:347）
        self.wheel_base = self.declare_parameter("wheel_base", 0.172).value
        self.test_mode = self.declare_parameter("test_mode", test_mode).value
        self.odom_x = 0.0
        self.odom_y = 0.0
        self.odom_yaw = 0.0
        self.last_left = None
        self.last_right = None
        self.last_odom_time_ns = None
        self.last_imu_data_raw = None
        self.last_imu_mag = None
        self.last_odom_raw = None
        self.last_voltage = None
        # Initialize the base controller with the UART port and baud rate
        if base_controller is not None:
            self.base_controller = base_controller
        elif self.test_mode:
            self.base_controller = DummyBaseController()
        else:
            self.base_controller = BaseController(_DEFAULT_SERIAL_PORT, 115200)
            self.get_logger().info(f"Serial port {_DEFAULT_SERIAL_PORT} opened at 115200 baud")
        # Timer to periodically execute the feedback loop
        if not self.test_mode:
            self.feedback_timer = self.create_timer(0.001, self.feedback_loop)

        # Subscribe to velocity commands and forward to chassis via existing serial connection.
        # ugv_driver is NOT launched separately to avoid serial port conflict.
        self.cmd_vel_sub_ = self.create_subscription(Twist, 'cmd_vel', self._cmd_vel_callback, 10)
        self.e_stop_active = False

        # E-stop: chassis is the single gatekeeper — blocks ALL cmd_vel sources (VLA, debug, etc.)
        self.create_subscription(Bool, 'e_stop', self._e_stop_callback, 10)
        # Watchdog: while e_stop active, hammer zero every 50ms to override any lagging cmd_vel
        self.create_timer(0.05, self._e_stop_watchdog)

        self.get_logger().info("ugv_bringup ready — publishing imu/data_raw, imu/mag, odom/odom_raw, voltage | subscribing cmd_vel, e_stop")

    # Main loop for reading sensor feedback and publishing it to ROS topics
    def feedback_loop(self):
        data = self.base_controller.feedback_data()
        if data is None:
            self.get_logger().warn("[bringup] feedback_data returned None (parse error), skipping frame",
                                   throttle_duration_sec=5.0)
            return
        if self.base_controller.base_data["T"] == 1001:  # Check if the feedback type is correct
            self.publish_imu_data_raw()  # Publish IMU raw data
            self.publish_imu_mag()  # Publish magnetic field data
            self.publish_odom_raw()  # Publish odometry data
            self.publish_voltage()  # Publish voltage data

    # Publish IMU data to the ROS topic "imu/data_raw"
    def publish_imu_data_raw(self):
        msg = Imu()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()  # Get the current timestamp
        msg.header.frame_id = "base_imu_link"
        imu_raw_data = self.base_controller.base_data

        # Populate the linear acceleration and angular velocity fields
        msg.linear_acceleration.x = 9.8 * float(imu_raw_data["ax"]) / 8192
        msg.linear_acceleration.y = 9.8 * float(imu_raw_data["ay"]) / 8192
        msg.linear_acceleration.z = 9.8 * float(imu_raw_data["az"]) / 8192
        
        msg.angular_velocity.x = 3.1415926 * float(imu_raw_data["gx"]) / (16.4 * 180)
        msg.angular_velocity.y = 3.1415926 * float(imu_raw_data["gy"]) / (16.4 * 180)
        msg.angular_velocity.z = 3.1415926 * float(imu_raw_data["gz"]) / (16.4 * 180)
              
        self.imu_data_raw_publisher_.publish(msg)
        self.last_imu_data_raw = msg
        
    # Publish magnetic field data to the ROS topic "imu/mag"
    def publish_imu_mag(self):
        msg = MagneticField()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()  # Get the current timestamp
        msg.header.frame_id = "base_imu_link"
        imu_raw_data = self.base_controller.base_data

        # Populate the magnetic field data
        msg.magnetic_field.x = float(imu_raw_data["mx"]) * 0.15
        msg.magnetic_field.y = float(imu_raw_data["my"]) * 0.15
        msg.magnetic_field.z = float(imu_raw_data["mz"]) * 0.15
              
        self.imu_mag_publisher_.publish(msg)
        self.last_imu_mag = msg

    # Publish odometry data to the ROS topic "odom/odom_raw"
    def publish_odom_raw(self):
        odom_raw_data = self.base_controller.base_data
        left_m  = float(odom_raw_data["odl"]) / 100.0
        right_m = float(odom_raw_data["odr"]) / 100.0
        now_ns  = self.get_clock().now().nanoseconds

        if self.last_odom_time_ns is None:
            # 首帧：以当前里程计值为基准，不计算差分，避免首帧跳变
            self.last_odom_time_ns = now_ns
            self.last_left  = left_m
            self.last_right = right_m
            return

        dt = max((now_ns - self.last_odom_time_ns) / 1e9, 1e-6)
        dl = left_m  - self.last_left
        dr = right_m - self.last_right
        self.last_odom_time_ns = now_ns
        self.last_left  = left_m
        self.last_right = right_m

        ds = (dl + dr) / 2.0
        vx = ds / dt

        # 噪声剔除：里程计跳变 >= 5 m/s 视为 ESP32 重启/溢出异常帧，丢弃
        if abs(vx) >= 5.0:
            self.get_logger().debug(f"[bringup] odometry spike ignored: vx={vx:.2f} dl={dl:.4f} dr={dr:.4f} dt={dt:.4f}")
            return

        if self.wheel_base > 0.0:
            dtheta = (dr - dl) / self.wheel_base
            wz = dtheta / dt
        else:
            # wheel_base 未配置时，用 IMU 陀螺仪 gz 代替轮差分角速度
            wz = math.pi * float(self.base_controller.base_data["gz"]) / (16.4 * 180)
            dtheta = wz * dt

        # 噪声剔除：角速度 >= 20 rad/s 为异常数据，角度不积分
        if abs(wz) >= 20.0:
            self.get_logger().debug(f"[bringup] gyro spike ignored: wz={wz:.2f}")
            return

        self.odom_yaw += dtheta
        self.odom_x   += ds * math.cos(self.odom_yaw)
        self.odom_y   += ds * math.sin(self.odom_yaw)

        msg = Odometry()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "odom"
        msg.child_frame_id  = "base_link"
        msg.pose.pose.position.x = self.odom_x
        msg.pose.pose.position.y = self.odom_y
        msg.pose.pose.position.z = 0.0
        msg.pose.pose.orientation.z = math.sin(self.odom_yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(self.odom_yaw / 2.0)
        msg.twist.twist.linear.x  = vx
        msg.twist.twist.angular.z = wz
        self.odom_publisher_.publish(msg)
        self.last_odom_raw = msg
        self.get_logger().info(
            f"[odom] vx={vx:.3f} wz={wz:.3f}  x={self.odom_x:.2f} y={self.odom_y:.2f} yaw={math.degrees(self.odom_yaw):.1f}°",
            throttle_duration_sec=5.0)

    def _e_stop_callback(self, msg: Bool) -> None:
        prev = self.e_stop_active
        self.e_stop_active = bool(msg.data)
        if self.e_stop_active and not prev:
            # Immediately send zero to UART
            self.base_controller.send_command({'T': 13, 'X': 0.0, 'Z': 0.0})
            self.get_logger().warn("[chassis] !! E-STOP — chassis halted, all cmd_vel ignored !!")
        elif not self.e_stop_active and prev:
            self.get_logger().info("[chassis] E-STOP released — chassis accepting cmd_vel again")

    def _e_stop_watchdog(self) -> None:
        """While e_stop is active, keep sending zero every 50ms to suppress lagging cmd_vel."""
        if self.e_stop_active and not self.test_mode:
            self.base_controller.send_command({'T': 13, 'X': 0.0, 'Z': 0.0})

    def _cmd_vel_callback(self, msg: Twist):
        """Forward /cmd_vel to chassis UART using the same serial held by base_controller."""
        if self.test_mode or self.e_stop_active:
            return
        vx = msg.linear.x
        wz = msg.angular.z
        # Apply minimum angular threshold when no linear motion (mirrored from ugv_driver)
        if vx == 0.0:
            if 0 < wz < 0.2:
                wz = 0.2
            elif -0.2 < wz < 0:
                wz = -0.2
        payload = {'T': 13, 'X': round(float(vx), 4), 'Z': round(float(wz), 4)}
        self.base_controller.send_command(payload)
        self.get_logger().info(
            f"[cmd_vel→uart] vx={vx:.3f}  wz={wz:.3f}",
            throttle_duration_sec=1.0,
        )

    # Publish voltage data to the ROS topic "voltage"
    def publish_voltage(self):
        voltage_data = self.base_controller.base_data
        msg = Float32()
        msg.data = float(voltage_data["v"])/100
        self.voltage_publisher_.publish(msg)
        self.last_voltage = msg
        self.get_logger().info(f"[voltage] {msg.data:.2f} V", throttle_duration_sec=10.0)
                        
# Main function to initialize the ROS node and start spinning
def main(args=None):
    rclpy.init(args=args)  # Initialize ROS
    node = ugv_bringup()  # Create the UGV bringup node
    rclpy.spin(node)  # Keep the node running
    #node.destroy_node()  # (optional) Shutdown the node
    rclpy.shutdown()  # Shutdown ROS

if __name__ == '__main__':
    main()
