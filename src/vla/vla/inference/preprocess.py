import numpy as np
from typing import Dict, Any

class InputMapper:
    """
    Maps raw ROS data (from SharedBuffer) to the feature dictionary expected by LeRobot.
    """
    def __init__(self):
        # image key must match the key used during data collection (ugv_data_collector camera_obs_key)
        self.image_key = "observation.images.camera"
        self.state_key = "observation.state"
        self.task_key = "task"

    def map(self, snapshot_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert snapshot data (numpy/strings) to the dict structure expected by LeRobot's processor.
        """
        mapped = {}
        
        # 1. Image
        if snapshot_data.get("image") is not None:
            mapped[self.image_key] = snapshot_data["image"]

        # 2. State (Proprioception)
        # We map Odometry to 'observation.state'.
        if snapshot_data.get("odom") is not None:
            odom = snapshot_data["odom"]
            # Construct a state vector. 
            # UGV State Space Adaptation: [vx, wz]
            # We strictly use Linear Velocity X and Angular Velocity Z.
            # This matches the action space (differential drive control) and minimizes 
            # the gap between simulation/training and reality.
            # Note: SmolVLA will automatically pad this to max_state_dim if needed.
            vx = odom["linear_velocity"][0]
            wz = odom["angular_velocity"][2]
            
            state_vec = np.array([vx, wz], dtype=np.float32)
            mapped[self.state_key] = state_vec
        
        # 3. Task (Instruction)
        # Ensure it's a string
        mapped[self.task_key] = snapshot_data.get("instruction") or ""

        return mapped
