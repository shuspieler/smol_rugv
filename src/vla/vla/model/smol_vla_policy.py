import sys
import os

# ── Jetson Orin CUDA allocator fix (MUST run before `import torch`) ──────────
# Jetson's nvmap kernel driver cannot satisfy the large contiguous allocations
# that PyTorch's CUDACachingAllocator requests on unified memory (CMA pool is
# only 256 MB).  Disabling the caching allocator forces per-tensor cudaMalloc,
# which succeeds because individual tensors are small.  The overhead is
# negligible for inference workloads.
# `expandable_segments:True` does NOT help — the nvmap failure occurs at the
# CUDA driver level, below any PyTorch allocator strategy.
os.environ.setdefault('PYTORCH_NO_CUDA_MEMORY_CACHING', '1')
# ─────────────────────────────────────────────────────────────────────────────

import torch
import logging
from typing import Tuple, Dict, Any

# Path hacking to include lerobot
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# Attempt to find 'ref_code' by traversing up or using environment variable
# Priority: ENV > Relative Path
LEROBOT_SRC = os.environ.get("LEROBOT_SRC")

if not LEROBOT_SRC:
    # Fallback to relative path assuming standard workspace layout: src/vla/vla/model -> ... -> ref_code
    # model -> vla -> vla -> src -> my_ugv_root -> ref_code
    # This assumes the package is installed in a way that preserves relative structure to ref_code, 
    # which is true for symlink install but fragile otherwise.
    # A more robust way in production is to install lerobot as a python package.
    PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "../../../../.."))
    LEROBOT_SRC = os.path.join(PROJECT_ROOT, "ref_code", "lerobot-main (SmolVLA)", "src")

if os.path.exists(LEROBOT_SRC) and LEROBOT_SRC not in sys.path:
    sys.path.append(LEROBOT_SRC)
else:
    logging.warning(f"LeRobot source not found at {LEROBOT_SRC}. Ensure 'ref_code' exists or set LEROBOT_SRC env var.")

try:
    from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
    from lerobot.policies.factory import make_pre_post_processors
except ImportError as e:
    logging.warning(f"Could not import lerobot: {e}. Ensure ref_code is present and dependencies are installed.")
    SmolVLAPolicy = None

class SmolVLAPolicyWrapper:
    """
    Wrapper for the SmolVLA policy from LeRobot.
    Handles model loading, FP16 conversion, and processor initialization.
    """
    def __init__(self, model_id: str, device: str = "cuda"):
        if SmolVLAPolicy is None:
            raise ImportError("LeRobot library not found or failed to import.")

        self.logger = logging.getLogger("SmolVLAPolicy")
        
        # Check if cuda is actually available
        if device == "cuda" and not torch.cuda.is_available():
            self.logger.warning("CUDA not available, falling back to CPU.")
            device = "cpu"
            
        self.device = torch.device(device)
        
        self.logger.info(f"Loading SmolVLA model: {model_id} on {self.device}...")

        try:
            # ── Jetson CUDA fix: force VLM backbone to load on CPU ────────────────
            # transformers 4.50+ uses meta-device loading (device_map dispatch) and
            # caching_allocator_warmup, both of which crash on Jetson's unified-memory
            # CUDA driver (NvMapMemAllocInternalTagged error 12 / CUDACachingAllocator
            # assert failure).
            # Fix: patch the AutoModelForImageTextToText reference *inside*
            # smolvlm_with_expert's module namespace (it was imported at module load
            # time, so patching transformers.AutoModelForImageTextToText has no effect).
            # After CPU loading we move the whole policy to the target device normally.
            _patched_vlm = False
            _patched_st = False
            _patched_module_to = False
            try:
                # Patch 1: transformers AutoModelForImageTextToText → force CPU
                # (smolvlm_with_expert imports it at module level, so patch the
                #  module-namespace reference, not transformers.Auto…)
                import lerobot.policies.smolvla.smolvlm_with_expert as _smolvlm_mod
                _orig_auto_cls = _smolvlm_mod.AutoModelForImageTextToText

                class _CPUOnlyAutoModel:
                    @classmethod
                    def from_pretrained(cls, m, **kw):
                        kw['device_map'] = 'cpu'
                        return _orig_auto_cls.from_pretrained(m, **kw)

                _smolvlm_mod.AutoModelForImageTextToText = _CPUOnlyAutoModel
                _patched_vlm = True

                # Patch 2: safetensors load_file → force CPU
                # lerobot's pretrained.py loads the fine-tuned checkpoint via
                # safetensors.torch.load_file(filename, device=config.device)
                # where config.device is "cuda". We force "cpu" here too.
                import safetensors.torch as _st_mod
                _orig_st_load_file = _st_mod.load_file

                def _cpu_load_file(filename, device=None, **kw):
                    return _orig_st_load_file(filename, device="cpu", **kw)

                _st_mod.load_file = _cpu_load_file
                _patched_st = True

                # Patch 3: torch.nn.Module.to → intercept .to("cuda") calls
                # lerobot's pretrained.py calls policy.to(config.device) at the end
                # of from_pretrained. We block all CUDA moves during the load; our
                # wrapper does the real .to(self.device) afterwards.
                import torch.nn as _nn_mod
                _orig_module_to = _nn_mod.Module.to

                def _noop_cuda_module_to(self_mod, *args, **kwargs):
                    # If the target is a CUDA device, skip — do nothing
                    dest = args[0] if args else kwargs.get('device', None)
                    if dest is not None:
                        if isinstance(dest, str) and dest.startswith("cuda"):
                            return self_mod
                        if isinstance(dest, torch.device) and dest.type == "cuda":
                            return self_mod
                    return _orig_module_to(self_mod, *args, **kwargs)

                _nn_mod.Module.to = _noop_cuda_module_to
                _patched_module_to = True

                self.logger.info("Jetson patch: all weights will load to CPU first.")
            except Exception as _pe:
                self.logger.warning(f"Jetson CPU-load patch could not be applied: {_pe}")
            # ──────────────────────────────────────────────────────────────────────

            try:
                self.policy = SmolVLAPolicy.from_pretrained(model_id)
            finally:
                if _patched_vlm:
                    _smolvlm_mod.AutoModelForImageTextToText = _orig_auto_cls
                if _patched_st:
                    _st_mod.load_file = _orig_st_load_file
                if _patched_module_to:
                    _nn_mod.Module.to = _orig_module_to

            self.logger.info(f"Model loaded to CPU, normalising to float32 on CPU then moving to {self.device}...")
            # Normalise all weights to float32 while still on CPU (cheap, no CUDA alloc).
            # The VLM backbone loads as bfloat16 (lerobot's torch_dtype setting); action
            # heads are already float32.  Unifying on CPU avoids a double-allocation on
            # the device.
            self.policy.float()
            # Pre-warm the CUDA context with a trivial tensor so the caching
            # allocator initialises before moving the full model.
            if self.device.type == 'cuda':
                _warm = torch.zeros(1, device=self.device)
                del _warm
                torch.cuda.empty_cache()
            self.policy.to(self.device)
            
            # --- VLA Adaptation for UGV ---
            # 1. Force disable Aloha-specific adaptations (joint flipping/gripper conversion)
            #    This is critical because our action space is [v, w], not mechanical arm joints.
            if hasattr(self.policy.config, 'adapt_to_pi_aloha') and self.policy.config.adapt_to_pi_aloha:
                self.logger.warning("Disabling 'adapt_to_pi_aloha' in config to prevent invalid action transformation for UGV.")
                self.policy.config.adapt_to_pi_aloha = False
                
            # 2. Check Action Dimension
            #    We expect 2 dimensions (v, w). If the loaded model has more (e.g., original 14D model),
            #    we log a warning but proceed (the inference loop will handle slicing).
            expected_action_dim = 2
            if self.policy.config.max_action_dim != expected_action_dim:
                self.logger.warning(
                    f"Model action dimension mismatch! Expected {expected_action_dim} (v, w), "
                    f"but got {self.policy.config.max_action_dim}. "
                    "Ensure you are using the fine-tuned UGV model. "
                    "Inference will proceed but actions may be sliced."
                )
            # -----------------------------

            self.policy.eval()
            
            # Initialize processors
            self.logger.info("Initializing pre/post processors...")
            self.preprocess_pipeline, self.postprocess_pipeline = make_pre_post_processors(
                self.policy.config,
                pretrained_name_or_path=model_id,
                preprocessor_overrides={"device_processor": {"device": str(self.device)}}
            )
            
            self.logger.info("Model loaded successfully.")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize SmolVLA: {e}")
            raise

    def preprocess(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run the preprocessing pipeline.
        Args:
            observation: Dict of numpy arrays (raw data from ROS).
        Returns:
            Dict of torch tensors on device.
        """
        # The pipeline expects a specific structure. 
        # Typically keys like 'observation.images.camera1', 'observation.state', etc.
        # This mapping should be handled before calling this, or the observation dict passed here
        # must already match what the processor expects.
        return self.preprocess_pipeline(observation)

    def step(self, batch: Dict[str, Any]) -> torch.Tensor:
        """
        Run inference.
        Args:
            batch: Preprocessed batch.
        Returns:
            Action tensor (normalized).
        """
        # Move all tensors to model device (preprocess pipeline may leave some on CPU).
        # Add batch dim if missing (preprocess returns unbatched tensors for single obs).
        # Cast uint8 images to float32; model is fully float32 (policy.float() in __init__).
        model_dtype = next(self.policy.parameters()).dtype  # expected: float32
        batch_on_device = {}
        for k, v in batch.items():
            if isinstance(v, torch.Tensor):
                t = v.to(self.device)
                # Add batch dimension: images (3,H,W)→(1,3,H,W), state (D,)→(1,D)
                if t.ndim == 3 and k.startswith('observation.images'):
                    t = t.unsqueeze(0)
                elif t.ndim == 1 and k == 'observation.state':
                    t = t.unsqueeze(0)
                # Only cast uint8 images to float32; leave everything else as-is
                if t.dtype == torch.uint8:
                    t = t.to(torch.float32)
                batch_on_device[k] = t
            else:
                batch_on_device[k] = v
        with torch.no_grad():
            actions_shape = (
                1,
                self.policy.config.chunk_size,
                self.policy.config.max_action_dim,
            )
            noise = torch.randn(actions_shape, dtype=torch.float32, device=self.device)

            # Use select_action() — it has @torch.no_grad() which keeps inference
            # fast (~25ms).  predict_action_chunk() lacks that decorator and causes
            # PyTorch to build a full autograd graph, ballooning inference to ~5700ms.
            #
            # select_action() fills SmolVLA's internal ACTION deque (chunk_size items)
            # and pops item[0].  We immediately drain the remaining items and reassemble
            # the full (1, N, D) chunk for our own ActionQueue (RHC).
            # Clearing the internal deque ensures the NEXT call always triggers fresh
            # inference instead of serving stale cached actions.
            first_action = self.policy.select_action(batch_on_device, noise=noise)
            # first_action: (1, action_dim)

            internal_q = self.policy._queues.get("action")
            if internal_q:
                remaining = list(internal_q)   # [(1, D), …]  up to chunk_size-1 items
                internal_q.clear()
            else:
                remaining = []

            all_actions = [first_action] + remaining  # list of (1, D) tensors
            chunk = torch.stack(all_actions, dim=1)   # (1, N, D)
            return chunk

    def postprocess(self, action: torch.Tensor) -> torch.Tensor:
        """
        Unnormalize the action.
        """
        return self.postprocess_pipeline(action)
