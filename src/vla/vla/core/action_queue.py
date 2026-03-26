import threading
import numpy as np
from collections import deque
from typing import Optional, Tuple

class ActionQueue:
    """
    Thread-safe queue to store action sequences (chunks) from the VLA model.
    The Control Loop consumes actions from this queue at a fixed frequency.
    """
    def __init__(self, max_len: int = 100):
        self._lock = threading.Lock()
        # We use a deque of (vx, wz) tuples
        self._queue = deque(maxlen=max_len)
        
    def put_chunk(self, actions: np.ndarray):
        """
        Add a chunk of actions to the queue.
        Strategy: Overwrite the remaining queue with the new chunk (Receding Horizon Control).
        
        Args:
            actions: numpy array of shape (N, D), where N is chunk size, D is action dim.
        """
        with self._lock:
            # Clear old actions as the new inference is more up-to-date
            # This implements the "Receding Horizon" strategy common in ACT/VLA
            self._queue.clear()
            
            # Parse actions
            for i in range(actions.shape[0]):
                action = actions[i]
                vx, wz = 0.0, 0.0
                
                if action.shape[0] == 2:
                    vx, wz = float(action[0]), float(action[1])
                elif action.shape[0] == 3:
                    # Assuming [vx, vy, wz] for holonomic, taking vx, wz for diff drive
                    vx, wz = float(action[0]), float(action[2])
                else:
                    # Fallback for unexpected shapes (should be handled by vla_loop)
                    # We default to stop (0,0)
                    pass
                
                self._queue.append((vx, wz))

    def get_next_action(self) -> Optional[Tuple[float, float]]:
        """
        Consume the next action from the queue.
        Returns:
            (vx, wz) tuple or None if queue is empty.
        """
        with self._lock:
            if not self._queue:
                return None
            return self._queue.popleft()
    
    def remaining(self) -> int:
        """Return the number of actions remaining in the queue."""
        with self._lock:
            return len(self._queue)

    def clear(self):
        with self._lock:
            self._queue.clear()
