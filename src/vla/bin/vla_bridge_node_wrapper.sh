#!/bin/bash
# VLA Bridge Node Wrapper Script
# 在 conda lerobot2 虚拟环境中运行 vla_bridge_node
# 允许 VLA 节点使用虚拟环境的依赖，同时其他节点用系统 Python

set -e

# 虚拟环境路径
CONDA_ENV_PATH="/home/jetson/miniforge3/envs/lerobot2"

# 检查虚拟环境是否存在
if [ ! -d "$CONDA_ENV_PATH" ]; then
    echo "Error: conda environment not found at $CONDA_ENV_PATH"
    exit 1
fi

# 激活虚拟环境并运行 vla_bridge_node
source "$CONDA_ENV_PATH/bin/activate"

# 运行主程序（所有参数传递给主程序）
exec "$CONDA_ENV_PATH/bin/python3" -m vla.vla_bridge_node "$@"
