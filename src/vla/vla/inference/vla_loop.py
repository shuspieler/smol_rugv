import threading
import time
import torch
import numpy as np
from typing import Any

from vla.core.shared_buffer import SharedBuffer
from vla.core.sync_policy import SyncPolicy
from vla.core.action_queue import ActionQueue
from vla.model.smol_vla_policy import SmolVLAPolicyWrapper
from vla.inference.preprocess import InputMapper

class VLALoop(threading.Thread):
    """
    Main inference loop running in a separate thread.
    Fetches data from buffer -> Preprocesses -> Runs Model -> Pushes Action Chunk to Queue.
    """
    # Trigger a new inference when the queue drops below this many steps.
    # With chunk_size=50 and control_rate=20Hz, 50 steps = 2.5s of actions.
    # Triggering at 10 steps (~0.5s remaining) gives enough lead time for inference.
    REFILL_THRESHOLD = 10
    POLL_INTERVAL = 0.02  # 20ms polling loop

    def __init__(self, 
                 buffer: SharedBuffer, 
                 action_queue: ActionQueue,
                 io: Any, # ROSIO type
                 model_id: str,
                 frequency: float = 10.0):
        super().__init__()
        self.buffer = buffer
        self.action_queue = action_queue
        self.io = io
        self.frequency = frequency
        self.running = False
        self.logger = io.node.get_logger()  # Use ROS logger from io.node
        
        # Initialize components
        self.sync_policy = SyncPolicy(logger=self.logger)
        self.input_mapper = InputMapper()
        
        self.logger.info("Initializing VLA Model (this may take time)...")
        self.model = SmolVLAPolicyWrapper(model_id)
        
        # State flags
        self.has_warned_action_dim = False
        
    def run(self):
        self.running = True
        self.logger.info(
            f"VLA Inference Loop started (refill_threshold={self.REFILL_THRESHOLD} steps, "
            f"poll_interval={self.POLL_INTERVAL*1000:.0f}ms)."
        )

        while self.running:
            # Trigger inference only when the queue is running low.
            # This adapts naturally to the actual inference latency on the hardware.
            if self.action_queue.remaining() < self.REFILL_THRESHOLD:
                try:
                    self._step()
                except Exception as e:
                    self.logger.error(f"Error in inference loop: {e}")

            time.sleep(self.POLL_INTERVAL)

    def _step(self):
        try:
            # 1. Get data
            snapshot = self.buffer.get_snapshot()
            
            # 2. Validate
            # Use ROS time for sync check
            current_time = self.io.node.get_clock().now().nanoseconds * 1e-9
            if not self.sync_policy.is_valid(snapshot, current_time):
                # Data not fresh enough, skip inference
                # (logging is handled within sync_policy.is_valid)
                return

            # 3. Map inputs
            try:
                features = self.input_mapper.map(snapshot["data"])
            except Exception as e:
                self.logger.error(f"Input mapping failed: {e}")
                return
            
            # 4. Preprocess (to Tensor)
            try:
                features_tensor = self.model.preprocess(features)
            except Exception as e:
                self.logger.error(f"Preprocessing failed: {e}")
                return
            
            # 5. Inference
            try:
                action_tensor = self.model.step(features_tensor)
            except Exception as e:
                self.logger.error(f"Model inference failed: {e}")
                return
            
            # 6. Postprocess
            try:
                action_numpy = self.model.postprocess(action_tensor)
            except Exception as e:
                self.logger.error(f"Postprocessing failed: {e}")
                return
            
            # 7. Push to Queue
            self._push_to_queue(action_numpy)
        except Exception as e:
            self.logger.error(f"Unexpected error in inference step: {e}")

    def _push_to_queue(self, action: Any):
        # Convert to CPU numpy if needed
        if isinstance(action, torch.Tensor):
            action = action.detach().cpu().numpy()
            
        # Handle batch dim (batch_size=1)
        if action.ndim == 3: # (B, T, D)
            action = action[0] 
            
        # action is now (T, D)
        # Verify it's 2D
        if action.ndim != 2:
            self.logger.warning(f"Unexpected action shape: {action.shape}, expected (T, D).")
            return
            
        # Adapt Action Space for UGV
        # We expect D=2 (vx, wz).
        # If D > 2 (e.g., using original 14D model), we slice the first 2 dimensions.
        # This allows us to test the pipeline even with mismatched models.
        if action.shape[1] > 2:
            if not self.has_warned_action_dim:
                self.logger.warning(f"Action dimension is {action.shape[1]}, slicing to first 2 for UGV (vx, wz).")
                self.has_warned_action_dim = True
            action = action[:, :2]
        elif action.shape[1] < 2:
            self.logger.error(f"Action dimension {action.shape[1]} is too small for UGV (needs 2: vx, wz).")
            return

        self.action_queue.put_chunk(action)

    def stop(self):
        self.running = False
        self.join()
