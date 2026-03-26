import numpy as np
from typing import Dict, Any

# Shape expected by the current pretrained model (mySmolVLAaloha_mobile_elevator).
# When fine-tuning on UGV data, a model with 1 camera and 2D state will be used,
# and these constants should be updated accordingly.
_MODEL_IMAGE_H = 256
_MODEL_IMAGE_W = 256
_MODEL_STATE_DIM = 6   # aloha_mobile state dim; our 2D state is padded with zeros
_MODEL_NUM_CAMERAS = 3 # camera1 is real, camera2/3 are black (zero-filled)

class InputMapper:
    """
    Maps raw ROS data (from SharedBuffer) to the feature dictionary expected by LeRobot.

    Key-name and dimension conventions are aligned to the currently loaded model.
    For the aloha_mobile_elevator pretrained model:
      - observation.images.camera1  →  real RGB image from the UGV camera
      - observation.images.camera2/3 → black (zero) placeholder images
      - observation.state           →  [vx, wz, 0, 0, 0, 0]  (padded to 6D)
    """
    def __init__(self):
        self.image_key   = "observation.images.camera1"  # matches model's camera1
        self.state_key   = "observation.state"
        self.task_key    = "task"

    def map(self, snapshot_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert snapshot data (numpy/strings) to the dict structure expected by LeRobot's processor.
        """
        mapped = {}

        # 1. Images
        # camera1 = real UGV camera; camera2/3 = black placeholders for missing cameras.
        if snapshot_data.get("image") is not None:
            mapped["observation.images.camera1"] = snapshot_data["image"]
        else:
            mapped["observation.images.camera1"] = np.zeros(
                (3, _MODEL_IMAGE_H, _MODEL_IMAGE_W), dtype=np.uint8
            )
        # Placeholder cameras required by the pretrained model.
        _black = np.zeros((3, _MODEL_IMAGE_H, _MODEL_IMAGE_W), dtype=np.uint8)
        mapped["observation.images.camera2"] = _black
        mapped["observation.images.camera3"] = _black

        # 2. State (Proprioception)
        # UGV provides [vx, wz]; pad to _MODEL_STATE_DIM with zeros for model compatibility.
        if snapshot_data.get("odom") is not None:
            odom = snapshot_data["odom"]
            vx = odom["linear_velocity"][0]
            wz = odom["angular_velocity"][2]
        else:
            vx, wz = 0.0, 0.0
        state_vec = np.zeros(_MODEL_STATE_DIM, dtype=np.float32)
        state_vec[0] = vx
        state_vec[1] = wz
        mapped[self.state_key] = state_vec

        # 3. Task (Instruction)
        mapped[self.task_key] = snapshot_data.get("instruction") or ""

        return mapped
