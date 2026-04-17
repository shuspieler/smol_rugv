#!/bin/bash
# LoRA checkpoint wrapper (uses local src/lerobot implementation)
# 用法：
#   bash src/vla/bin/vla_bridge_node_wrapper_lora.sh [lora_checkpoint_path] [extra ros args...]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

DEFAULT_LORA_CKPT="${PROJECT_ROOT}/models/smolvla_ugv_moveaway_lora_vlm_only"
BASE_CKPT_WRAPPER="${SCRIPT_DIR}/vla_bridge_node_wrapper_checkpoint.sh"

if [ ! -f "$BASE_CKPT_WRAPPER" ]; then
    echo "Error: base checkpoint wrapper not found: $BASE_CKPT_WRAPPER"
    exit 1
fi

LORA_CKPT="${1:-$DEFAULT_LORA_CKPT}"
if [ "$#" -ge 1 ]; then
    shift
fi

if [ ! -d "$LORA_CKPT" ]; then
    echo "Error: LoRA checkpoint path not found: $LORA_CKPT"
    exit 1
fi

# Force VLA runtime to use copied local lerobot implementation in this repo.
export LEROBOT_SRC="${PROJECT_ROOT}/src"

exec bash "$BASE_CKPT_WRAPPER" "$LORA_CKPT" "$@"