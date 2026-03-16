#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
import serial  
import json  
from sensor_msgs.msg import JointState
from std_msgs.msg import Float32, Float32MultiArray, Bool
import subprocess
import time
import os

def is_jetson():
    result = any("ugv_jetson" in root for root, dirs, files in os.walk("/"))
    return result

if is_jetson():
    serial_port = '/dev/ttyCH341USB0'
else:
    serial_port = '/dev/ttyAMA0'

class UgvDriver(Node):
    def __init__(self, name, serial_client=None, test_mode=False):
        super().__init__(name)
        self.test_mode = self.declare_parameter("test_mode", test_mode).value
        self.serial_port = self.declare_parameter("serial_port", serial_port).value
        self.serial_baud = self.declare_parameter("serial_baud", 115200).value
        self.ser = serial_client
        self.sent_json = []
        self.last_velocity_command = None
        if self.ser is None and not self.test_mode:
            self.ser = serial.Serial(self.serial_port, self.serial_baud, timeout=1)

        # Subscribe to velocity commands (cmd_vel topic)
        self.cmd_vel_sub_ = self.create_subscription(Twist, "cmd_vel", self.cmd_vel_callback, 10)
        self.e_stop_sub_ = self.create_subscription(Bool, "e_stop", self.e_stop_callback, 10)
        self.e_stop_active = False
        self.e_stop_timer_ = self.create_timer(0.05, self.e_stop_watchdog)

        # Subscribe to joint states (ugv/joint_states topic)
        self.joint_states_sub = self.create_subscription(JointState, 'ugv/joint_states', self.joint_states_callback, 10)

        # Subscribe to LED control data (ugv/led_ctrl topic)
        self.led_ctrl_sub = self.create_subscription(Float32MultiArray, 'ugv/led_ctrl', self.led_ctrl_callback, 10)

        # Subscribe to voltage data (voltage topic)
        self.voltage_sub = self.create_subscription(Float32, 'voltage', self.voltage_callback, 10)

    # Callback for processing velocity commands
    def cmd_vel_callback(self, msg):
        if self.e_stop_active:
            linear_velocity = 0.0
            angular_velocity = 0.0
        else:
            linear_velocity = msg.linear.x
            angular_velocity = msg.angular.z
        # Apply minimum threshold to angular velocity if linear velocity is zero
        if linear_velocity == 0:
            if 0 < angular_velocity < 0.2:
                angular_velocity = 0.2
            elif -0.2 < angular_velocity < 0:
                angular_velocity = -0.2

        # Send the velocity data to the UGV as a JSON string
        self.send_velocity(linear_velocity, angular_velocity)

    def send_json(self, payload):
        data = json.dumps(payload) + "\n"
        self.sent_json.append(payload)
        if self.ser is not None:
            self.ser.write(data.encode())

    def send_velocity(self, linear_velocity, angular_velocity):
        payload = {'T': '13', 'X': linear_velocity, 'Z': angular_velocity}
        self.last_velocity_command = payload
        self.send_json(payload)

    def e_stop_callback(self, msg):
        self.e_stop_active = bool(msg.data)
        if self.e_stop_active:
            self.send_velocity(0.0, 0.0)

    def e_stop_watchdog(self):
        if self.e_stop_active:
            self.send_velocity(0.0, 0.0)

    # Callback for processing joint state updates
    def joint_states_callback(self, msg):
        header = {
            'stamp': {
                'sec': msg.header.stamp.sec,
                'nanosec': msg.header.stamp.nanosec,
            },
            'frame_id': msg.header.frame_id,
        }

        # Extract joint positions and convert to degrees
        name = msg.name
        position = msg.position

        x_rad = position[name.index('pt_base_link_to_pt_link1')]
        y_rad = position[name.index('pt_link1_to_pt_link2')]

        x_degree = (180 * x_rad) / 3.1415926
        y_degree = (180 * y_rad) / 3.1415926

        # Send the joint data as a JSON string to the UGV
        joint_data = json.dumps({
            'T': 134, 
            'X': x_degree, 
            'Y': y_degree, 
            "SX": 600,
            "SY": 600,
        }) + "\n"
                
        if self.ser is not None:
            self.ser.write(joint_data.encode())

    # Callback for processing LED control commands
    def led_ctrl_callback(self, msg):
        IO4 = msg.data[0]
        IO5 = msg.data[1]
        
        # Send LED control data as a JSON string to the UGV
        led_ctrl_data = json.dumps({
            'T': 132, 
            "IO4": IO4,
            "IO5": IO5,
        }) + "\n"
                
        if self.ser is not None:
            self.ser.write(led_ctrl_data.encode())

    # Callback for processing voltage data
    def voltage_callback(self, msg):
        voltage_value = msg.data

        # If voltage drops below a threshold, play a low battery warning sound
        if 0.1 < voltage_value < 9: 
            subprocess.run(['aplay', '-D', 'plughw:3,0', '/home/ws/ugv_ws/src/ugv_main/ugv_bringup/ugv_bringup/low_battery.wav'])
            time.sleep(5)

def main(args=None):
    rclpy.init(args=args)
    node = UgvDriver("ugv_driver")
    
    try:
        rclpy.spin(node)  # Keep the node running and handling callbacks
    except KeyboardInterrupt:
        pass  # Graceful shutdown on user interrupt
    finally:
        node.destroy_node()
        rclpy.shutdown()
        if node.ser is not None:
            node.ser.close()

if __name__ == '__main__':
    main()
