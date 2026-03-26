import rclpy
from rclpy.node import Node
import logging

from vla.io.ros_io import ROSIO
from vla.core.shared_buffer import SharedBuffer
from vla.core.action_queue import ActionQueue
from vla.inference.vla_loop import VLALoop

class VLABridgeNode(Node):
    def __init__(self):
        super().__init__('vla_bridge_node')
        
        # Parameters
        self.declare_parameter('model_id', 'lerobot/smolvla_base')
        self.declare_parameter('inference_rate', 10.0) # Frequency of Model Inference
        self.declare_parameter('control_rate', 20.0)   # Frequency of Action Execution
        
        model_id = self.get_parameter('model_id').value
        inference_rate = self.get_parameter('inference_rate').value
        control_rate = self.get_parameter('control_rate').value
        
        self.get_logger().info(f"Starting VLABridgeNode with model {model_id}...")
        
        # Initialize components
        self.buffer = SharedBuffer()
        self.action_queue = ActionQueue(max_len=100)
        self.ros_io = ROSIO(self, self.buffer)
        self.vla_loop = None
        self.vla_loop_error = False
        
        # Start Inference Thread
        try:
            self.vla_loop = VLALoop(
                buffer=self.buffer,
                action_queue=self.action_queue,
                io=self.ros_io,
                model_id=model_id,
                frequency=inference_rate
            )
            self.vla_loop.start()
            self.get_logger().info("VLA inference loop started successfully.")
        except Exception as e:
            self.get_logger().error(f"Failed to start VLA Loop: {e}")
            self.get_logger().warn(
                "VLA node will operate in degraded mode: publishing zero velocity commands only. "
                "Check logs and model availability."
            )
            self.vla_loop_error = True
            # Note: We do NOT raise here. Node continues (like camera_node does with no device found).
            
        # Start Control Timer
        self.create_timer(1.0 / control_rate, self._control_loop)

        # Diagnostic status log every 5 seconds
        self._status_count = 0
        self.create_timer(5.0, self._status_log)

    def _status_log(self):
        self._status_count += 1
        lines = [f"── VLA Status #{self._status_count} {'─' * 30}"]

        # Per-topic Hz
        hz = self.ros_io.get_topic_hz()
        lines.append(
            f"  Topics  │ camera={hz['image']:.1f}Hz  "
            f"odom={hz['odom']:.1f}Hz  "
            f"imu={hz['imu']:.1f}Hz  "
            f"instr={hz['instruction']:.1f}Hz"
        )

        # Inference stats
        if self.vla_loop is not None and not self.vla_loop_error:
            s = self.vla_loop.get_stats()
            if s["last_action"]:
                action_str = f"vx={s['last_action'][0]:+.3f}  wz={s['last_action'][1]:+.3f}"
            else:
                action_str = "N/A (no inference yet)"
            lines.append(
                f"  Infer   │ #{s['infer_count']}  last={s['last_infer_ms']:.0f}ms  "
                f"queue={s['queue_depth']}  action=[{action_str}]"
            )
        else:
            lines.append("  Infer   │ DEGRADED (model not loaded)")

        self.get_logger().info("\n".join(lines))

    def _control_loop(self):
        """
        Consumes actions from the queue and publishes them.
        If VLA failed to initialize, publishes safe zero velocity.
        """
        if self.vla_loop_error:
            # Degraded mode: publish zero velocity for safety
            self.ros_io.publish_cmd_vel(0.0, 0.0)
            return
            
        action = self.action_queue.get_next_action()
        if action:
            vx, wz = action
            self.ros_io.publish_cmd_vel(vx, wz)
        else:
            # If queue is empty (inference too slow or stopped), stop the robot for safety
            self.ros_io.publish_cmd_vel(0.0, 0.0)

    def destroy_node(self):
        self.get_logger().info("Stopping VLA Bridge Node...")
        if self.vla_loop is not None and not self.vla_loop_error:
            self.get_logger().info("Stopping VLA inference loop...")
            self.vla_loop.stop()
            # Wait for thread with timeout to prevent hang on ARM64
            self.vla_loop.join(timeout=2.0)
            if self.vla_loop.is_alive():
                self.get_logger().warn("VLA loop thread did not terminate within timeout.")
        super().destroy_node()

def main(args=None):
    # Configure generic logging
    logging.basicConfig(level=logging.INFO)
    
    rclpy.init(args=args)
    node = None
    try:
        node = VLABridgeNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Node exited with error: {e}")
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

if __name__ == '__main__':
    main()
