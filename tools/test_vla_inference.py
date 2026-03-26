#!/usr/bin/env python3
# Jetson: set PYTORCH_CUDA_ALLOC_CONF before any torch import
import os
# Jetson CUDA fix: raw cudaMalloc (no caching pool) to avoid NVML assert / pool OOM
os.environ.setdefault('PYTORCH_NO_CUDA_MEMORY_CACHING', '1')

"""
Standalone VLA inference pipeline test.
Tests model loading, preprocessing, inference, and postprocessing
WITHOUT requiring ROS to be running.

Usage (from smol_rugv root):
    /home/jetson/miniforge3/envs/lerobot2/bin/python tools/test_vla_inference.py
"""
import sys
import os
import time
import numpy as np

# ── Path setup ──────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
VLA_SRC      = os.path.join(PROJECT_ROOT, "src", "vla")
MODEL_PATH   = os.path.join(
    PROJECT_ROOT,
    "models",
    "mySmolVLAaloha_mobile_elevator20000",
    "checkpoints",
    "last",
    "pretrained_model",
)

if VLA_SRC not in sys.path:
    sys.path.insert(0, VLA_SRC)

# ── Sanity checks ────────────────────────────────────────────────────────────
print("=" * 60)
print("VLA Inference Pipeline Test")
print("=" * 60)
print(f"  Model path : {MODEL_PATH}")
print(f"  VLA src    : {VLA_SRC}")
print()

if not os.path.isdir(MODEL_PATH):
    print(f"[FAIL] Model directory not found: {MODEL_PATH}")
    sys.exit(1)
print("[OK]  Model directory exists")

# ── Import check ─────────────────────────────────────────────────────────────
print()
print("--- Step 1: Import checks ---")
try:
    import torch
    print(f"[OK]  torch {torch.__version__} | CUDA: {torch.cuda.is_available()}")
except ImportError as e:
    print(f"[FAIL] torch: {e}"); sys.exit(1)

try:
    from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
    print("[OK]  SmolVLAPolicy")
except ImportError as e:
    print(f"[FAIL] SmolVLAPolicy: {e}"); sys.exit(1)

try:
    from vla.model.smol_vla_policy import SmolVLAPolicyWrapper
    from vla.inference.preprocess import InputMapper
    print("[OK]  SmolVLAPolicyWrapper, InputMapper")
except ImportError as e:
    print(f"[FAIL] vla modules: {e}"); sys.exit(1)

# ── Model loading ─────────────────────────────────────────────────────────────
print()
print("--- Step 2: Model loading ---")
t0 = time.time()
try:
    wrapper = SmolVLAPolicyWrapper(model_id=MODEL_PATH, device="cuda")
    print(f"[OK]  Model loaded in {time.time()-t0:.1f}s")
except Exception as e:
    print(f"[FAIL] Model loading: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# ── Synthetic observation ────────────────────────────────────────────────────
print()
print("--- Step 3: Preprocessing ---")

# Simulate what SharedBuffer would give us
fake_snapshot = {
    "image": np.random.randint(0, 255, (3, 256, 256), dtype=np.uint8),
    "odom": {
        "linear_velocity":  np.array([0.2, 0.0, 0.0]),   # vx = 0.2 m/s
        "angular_velocity": np.array([0.0, 0.0, 0.05]),  # wz = 0.05 rad/s
    },
    "instruction": "move forward",
}

mapper = InputMapper()
features = mapper.map(fake_snapshot)

# InputMapper already maps: camera → camera1/2/3, state [vx,wz] → [vx,wz,0,0,0,0]
# No additional compat shim needed.

print(f"[OK]  InputMapper output keys: {list(features.keys())}")
for k, v in features.items():
    if isinstance(v, np.ndarray):
        print(f"        {k}: shape={v.shape}, dtype={v.dtype}")
    else:
        print(f"        {k}: {repr(v)}")

try:
    t1 = time.time()
    features_tensor = wrapper.preprocess(features)
    print(f"[OK]  Preprocess done in {(time.time()-t1)*1000:.1f}ms")
    for k, v in features_tensor.items():
        if hasattr(v, 'shape'):
            print(f"        {k}: shape={tuple(v.shape)}, dtype={v.dtype}, device={v.device}")
except Exception as e:
    print(f"[FAIL] Preprocess: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# ── Inference (20 steps) ─────────────────────────────────────────────────────
print()
print("--- Step 4: Inference (20 steps) ---")
N_STEPS = 20
inference_times = []
try:
    for i in range(N_STEPS):
        t2 = time.time()
        action_tensor = wrapper.step(features_tensor)
        step_ms = (time.time() - t2) * 1000
        inference_times.append(step_ms)
        print(f"  step {i+1:2d}/{N_STEPS}: {step_ms:.1f}ms  shape={tuple(action_tensor.shape)}")
    inference_ms = np.mean(inference_times)
    print(f"[OK]  20 steps done | avg={inference_ms:.1f}ms  min={min(inference_times):.1f}ms  max={max(inference_times):.1f}ms")
except Exception as e:
    print(f"[FAIL] Inference step {len(inference_times)+1}: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# ── Postprocessing ────────────────────────────────────────────────────────────
print()
print("--- Step 5: Postprocessing (last action) ---")
try:
    action_raw = wrapper.postprocess(action_tensor)
    if isinstance(action_raw, dict):
        action_np = action_raw.get("action")
        if hasattr(action_np, 'numpy'):
            action_np = action_np.detach().cpu().numpy()
    elif hasattr(action_raw, 'detach'):
        action_np = action_raw.detach().cpu().numpy()
    else:
        action_np = np.array(action_raw)

    # Handle batch dim
    if action_np.ndim == 3:
        action_np = action_np[0]   # (T, D)

    print(f"[OK]  Postprocess done")
    print(f"        action shape       : {action_np.shape}")
    print(f"        action (first step): {action_np[0]}")

    # Show the 2D slice we'd actually send to chassis
    vx_wz = action_np[:, :2]
    print(f"        vx/wz first 5 steps:\n{vx_wz[:5]}")
except Exception as e:
    print(f"[FAIL] Postprocess: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("ALL STEPS PASSED")
print(f"  Inference steps   : {N_STEPS}")
print(f"  Avg latency       : {inference_ms:.1f}ms")
print(f"  Min / Max         : {min(inference_times):.1f}ms / {max(inference_times):.1f}ms")
print(f"  Total time        : {(time.time()-t0):.1f}s")
print("=" * 60)
