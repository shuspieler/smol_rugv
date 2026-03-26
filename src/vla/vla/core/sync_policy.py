import time
from typing import Dict, Any, Optional, Any as LoggerType

class SyncPolicy:
    """
    Policy to determine if the current snapshot of data is valid for inference.
    """
    def __init__(self, image_timeout: float = 0.5, odom_timeout: float = 0.2, logger: Optional[LoggerType] = None):
        self.image_timeout = image_timeout
        self.odom_timeout = odom_timeout
        self.logger = logger  # Accept optional ROS logger

    def is_valid(self, snapshot: Dict[str, Any], current_time: float) -> bool:
        """
        Check if the snapshot has fresh and valid data.
        Args:
            snapshot: Data snapshot from buffer
            current_time: Current system/ROS time in seconds (float)
        """
        data = snapshot["data"]
        timestamps = snapshot["timestamps"]
        
        # 1. Check Image existence and freshness
        if data["image"] is None:
            if self.logger:
                self.logger.debug("No image data available.")
            return False
            
        image_age = current_time - timestamps["image"]
        if image_age > self.image_timeout:
            if self.logger:
                self.logger.debug(f"Image data is stale. Delay: {image_age:.3f}s")
            return False

        # 2. Check Odom existence (optional when chassis not running)
        # If odom is absent, inference continues with zero state (degraded but functional).
        if data["odom"] is None:
            if self.logger:
                self.logger.warn(
                    "No odom data — running inference with zero state. Start chassis node for full operation.",
                    throttle_duration_sec=10.0
                )
            return True  # allow inference with zero state via InputMapper fallback

        # Odom is high frequency, should be very fresh
        odom_age = current_time - timestamps["odom"]
        if odom_age > self.odom_timeout:
            if self.logger:
                self.logger.debug(f"Odom data is stale. Delay: {odom_age:.3f}s")
            return False

        return True
