#!/bin/bash
# VLA checkpoint wrapper
# 用法：
#   bash src/vla/bin/vla_bridge_node_wrapper_checkpoint.sh <model_id_or_local_checkpoint_path> [extra ros args...]
# 示例：
#   bash src/vla/bin/vla_bridge_node_wrapper_checkpoint.sh /home/jetson/Shu/smol_rugv/models/smolvla_ugv_moveaway_finetune/checkpoints/last/pretrained_model
#   MEM_DEFRAG_ON_START=1 bash src/vla/bin/vla_bridge_node_wrapper_checkpoint.sh /home/jetson/Shu/smol_rugv/models/smolvla_ugv_moveaway_finetune/checkpoints/last/pretrained_model

set -e

if [ "$#" -lt 1 ]; then
    echo "Usage: bash src/vla/bin/vla_bridge_node_wrapper_checkpoint.sh <model_id_or_local_checkpoint_path> [extra ros args...]"
    exit 1
fi

MODEL_ID="$1"
shift

# Default instruction fallback for single-task moveaway checkpoints.
# Can be overridden by env var or extra ros args.
DEFAULT_INSTRUCTION="${DEFAULT_INSTRUCTION:-move away from the column}"

# If input looks like a local path, validate directory exists.
if [[ "$MODEL_ID" == /* || "$MODEL_ID" == ./* || "$MODEL_ID" == ../* ]]; then
    if [ ! -d "$MODEL_ID" ]; then
        echo "Error: checkpoint path not found: $MODEL_ID"
        exit 1
    fi

    # Auto-resolve common checkpoint directory layouts when config.json is not at root.
    if [ ! -f "$MODEL_ID/config.json" ]; then
        if [ -f "$MODEL_ID/checkpoints/last/pretrained_model/config.json" ]; then
            echo "[INFO] Resolved model root to: $MODEL_ID/checkpoints/last/pretrained_model"
            MODEL_ID="$MODEL_ID/checkpoints/last/pretrained_model"
        elif [ -f "$MODEL_ID/pretrained_model/config.json" ]; then
            echo "[INFO] Resolved model root to: $MODEL_ID/pretrained_model"
            MODEL_ID="$MODEL_ID/pretrained_model"
        elif [ -f "$MODEL_ID/last/pretrained_model/config.json" ]; then
            echo "[INFO] Resolved model root to: $MODEL_ID/last/pretrained_model"
            MODEL_ID="$MODEL_ID/last/pretrained_model"
        else
            echo "Error: config.json not found under: $MODEL_ID"
            echo "Hint: pass a directory that contains config.json, e.g. */checkpoints/last/pretrained_model"
            exit 1
        fi
    fi
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Compatibility bridge:
# Newer training pipelines may persist LoRA-related SmolVLAConfig fields even
# for non-LoRA checkpoints. The legacy ref_code lerobot config cannot parse
# these fields. If we detect them in local config.json, switch to the local
# src/lerobot implementation that supports the extended config.
if [ -z "${LEROBOT_SRC:-}" ] && [ -f "$MODEL_ID/config.json" ]; then
    if grep -q '"use_lora"\s*:' "$MODEL_ID/config.json"; then
        if [ -d "$PROJECT_ROOT/src" ]; then
            export LEROBOT_SRC="$PROJECT_ROOT/src"
            echo "[INFO] Detected LoRA config fields in checkpoint; using LEROBOT_SRC=$LEROBOT_SRC"
        fi
    fi
fi

BASE_WRAPPER="$SCRIPT_DIR/vla_bridge_node_wrapper.sh"

if [ ! -f "$BASE_WRAPPER" ]; then
    echo "Error: base wrapper not found: $BASE_WRAPPER"
    exit 1
fi

exec bash "$BASE_WRAPPER" --ros-args -p model_id:="$MODEL_ID" -p default_instruction:="$DEFAULT_INSTRUCTION" "$@"
