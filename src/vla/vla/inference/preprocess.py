import numpy as np
from typing import Dict, Any

# Runtime input layout for the current UGV checkpoint.
_MODEL_IMAGE_H = 256
_MODEL_IMAGE_W = 256
_MODEL_STATE_DIM = 2   # [vx, wz] to match checkpoint normalizer stats
_MODEL_NUM_CAMERAS = 3 # camera1 is real, camera2/3 are black (zero-filled)

class InputMapper:
    """
    Maps raw ROS data (from SharedBuffer) to the feature dictionary expected by LeRobot.

        Key-name and dimension conventions are aligned to the currently loaded model.
        For the current UGV checkpoint:
      - observation.images.camera1  →  real RGB image from the UGV camera
      - observation.images.camera2/3 → black (zero) placeholder images
            - observation.state           →  [vx, wz]  (2D)
    """
    def __init__(self, default_instruction: str = "", logger=None):
        self.image_key   = "observation.images.camera1"  # matches model's camera1
        self.state_key   = "observation.state"
        self.task_key    = "task"
        self.default_instruction = (default_instruction or "").strip()
        self.logger = logger
        self._warned_missing_instruction = False

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
        # Use 2D [vx, wz] to match checkpoint normalizer stats.
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
        instruction = snapshot_data.get("instruction")
        if isinstance(instruction, str):
            instruction = instruction.strip()
        if not instruction:
            instruction = self.default_instruction
            if instruction and self.logger and not self._warned_missing_instruction:
                self.logger.warn(
                    f"No /instruction_text received, using default_instruction='{instruction}'.",
                    throttle_duration_sec=10.0,
                )
                self._warned_missing_instruction = True
        mapped[self.task_key] = instruction or ""

        return mapped
