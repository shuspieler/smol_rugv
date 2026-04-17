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

# If input looks like a local path, validate directory exists.
if [[ "$MODEL_ID" == /* || "$MODEL_ID" == ./* || "$MODEL_ID" == ../* ]]; then
    if [ ! -d "$MODEL_ID" ]; then
        echo "Error: checkpoint path not found: $MODEL_ID"
        exit 1
    fi
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_WRAPPER="$SCRIPT_DIR/vla_bridge_node_wrapper.sh"

if [ ! -f "$BASE_WRAPPER" ]; then
    echo "Error: base wrapper not found: $BASE_WRAPPER"
    exit 1
fi

exec bash "$BASE_WRAPPER" --ros-args -p model_id:="$MODEL_ID" "$@"
