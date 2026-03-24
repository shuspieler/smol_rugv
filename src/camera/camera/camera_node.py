"""
camera_node.py — ROS2 camera publisher for smol_rugv.

Captures frames from a USB camera via OpenCV (cv2.VideoCapture) and
publishes them as sensor_msgs/Image on the 'image_raw' topic under the
node's namespace.  The driver is intentionally lightweight: no perception,
no inference, no synchronisation — just raw frames on the bus.

Topic  : image_raw  (sensor_msgs/Image, encoding bgr8)
QoS    : BestEffort / Volatile / depth 10  (matches debug_node & vla_bridge_node)
Params : video_device  (str)  device path, default "/dev/video0"
         image_width   (int)  default 640
         image_height  (int)  default 480
         framerate     (float) default 30.0
         frame_id      (str)  tf frame, default "camera_link"
"""

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)
from sensor_msgs.msg import Image

# ── QoS profile shared with subscribers in debug_node / vla_bridge_node ────
_SENSOR_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    durability=QoSDurabilityPolicy.VOLATILE,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=10,
)


class CameraNode(Node):
    """Capture from a USB camera and publish frames to ROS2."""

    def __init__(self) -> None:
        super().__init__("camera_node")

        # ── Parameters ────────────────────────────────────────────────────
        self.declare_parameter("video_device", "/dev/video0")
        self.declare_parameter("image_width", 640)
        self.declare_parameter("image_height", 480)
        self.declare_parameter("framerate", 30.0)
        self.declare_parameter("frame_id", "camera_link")

        device_path: str = self.get_parameter("video_device").value
        width: int      = self.get_parameter("image_width").value
        height: int     = self.get_parameter("image_height").value
        fps: float      = self.get_parameter("framerate").value
        self._frame_id: str = self.get_parameter("frame_id").value

        # ── Camera open: try declared path → auto-detect(-1) → index 0 ──
        self._cap: cv2.VideoCapture | None = None
        for dev in (device_path, -1, 0):
            cap = cv2.VideoCapture(dev)
            if cap.isOpened():
                self._cap = cap
                self.get_logger().info(f"Camera opened: {dev}")
                break
            cap.release()

        if self._cap is None:
            self.get_logger().error(
                "No camera device found! Node will spin but publish nothing."
            )
        else:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self._cap.set(cv2.CAP_PROP_FPS, fps)
            # Read back actual resolution (camera may not honour the request)
            actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.get_logger().info(
                f"Resolution: {actual_w}x{actual_h} @ {fps}fps"
            )

        # ── Publisher ─────────────────────────────────────────────────────
        self._bridge = CvBridge()
        self._pub = self.create_publisher(Image, "image_raw", _SENSOR_QOS)

        # ── Capture timer ─────────────────────────────────────────────────
        self._timer = self.create_timer(1.0 / fps, self._capture_cb)

        self.get_logger().info(
            f"CameraNode ready — publishing /{self.get_namespace()}/image_raw"
        )

    # ── Timer callback ─────────────────────────────────────────────────────
    def _capture_cb(self) -> None:
        if self._cap is None:
            return

        ok, frame = self._cap.read()
        if not ok:
            self.get_logger().warn("Camera read failed — attempting reopen on /dev/video0")
            self._cap.release()
            self._cap = cv2.VideoCapture(0)
            return

        msg = self._bridge.cv2_to_imgmsg(frame, encoding="bgr8")
        msg.header.stamp    = self.get_clock().now().to_msg()
        msg.header.frame_id = self._frame_id
        self._pub.publish(msg)

    # ── Cleanup ────────────────────────────────────────────────────────────
    def destroy_node(self) -> None:
        if self._cap is not None:
            self._cap.release()
        super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = CameraNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
