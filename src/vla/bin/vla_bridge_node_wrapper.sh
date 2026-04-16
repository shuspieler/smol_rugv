#!/bin/bash
# VLA Bridge Node Wrapper Script
# 在 conda lerobot2 虚拟环境中运行 vla_bridge_node
# 允许 VLA 节点使用虚拟环境的依赖，同时其他节点用系统 Python

set -e

# 可通过环境变量覆盖环境名（默认 lerobot2）
CONDA_ENV_NAME="${CONDA_ENV_NAME:-lerobot2}"

# 自动解析 conda base；失败时回退到常见路径
if command -v conda >/dev/null 2>&1; then
    CONDA_BASE="$(conda info --base)"
else
    CONDA_BASE="/home/jetson/miniforge3"
fi

# 虚拟环境路径
CONDA_ENV_PATH="${CONDA_BASE}/envs/${CONDA_ENV_NAME}"
CONDA_PYTHON="${CONDA_ENV_PATH}/bin/python3"

# 项目路径与 LeRobot 源码路径（用于消除 install 路径下的误判）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
DEFAULT_LEROBOT_SRC="${PROJECT_ROOT}/ref_code/lerobot-main (SmolVLA)/src"
DEFAULT_MEM_DEFRAG_SCRIPT="${PROJECT_ROOT}/defrag_memory.sh"

# 可选：启动前执行内存整理（适用于 Jetson 连续分配失败场景）
# 开关：MEM_DEFRAG_ON_START=1
# 脚本路径覆盖：MEM_DEFRAG_SCRIPT=/path/to/defrag_memory.sh
MEM_DEFRAG_ON_START="${MEM_DEFRAG_ON_START:-0}"
MEM_DEFRAG_SCRIPT="${MEM_DEFRAG_SCRIPT:-$DEFAULT_MEM_DEFRAG_SCRIPT}"

# 检查虚拟环境是否存在
if [ ! -d "$CONDA_ENV_PATH" ]; then
    echo "Error: conda environment not found at $CONDA_ENV_PATH"
    exit 1
fi

# 检查解释器是否存在
if [ ! -x "$CONDA_PYTHON" ]; then
    echo "Error: python3 not found in conda env at $CONDA_PYTHON"
    exit 1
fi

if [ -z "${LEROBOT_SRC:-}" ] && [ -d "$DEFAULT_LEROBOT_SRC" ]; then
    export LEROBOT_SRC="$DEFAULT_LEROBOT_SRC"
fi

if [ "$MEM_DEFRAG_ON_START" = "1" ]; then
    if [ -f "$MEM_DEFRAG_SCRIPT" ]; then
        echo "[INFO] Running memory defrag script: $MEM_DEFRAG_SCRIPT"
        bash "$MEM_DEFRAG_SCRIPT"
    else
        echo "[WARN] MEM_DEFRAG_ON_START=1 but script not found: $MEM_DEFRAG_SCRIPT"
    fi
fi

# 运行主程序（依赖 source install/setup.bash 提供的 PYTHONPATH）
exec "$CONDA_PYTHON" -m vla.vla_bridge_node "$@"
