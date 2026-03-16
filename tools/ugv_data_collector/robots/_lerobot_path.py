from __future__ import annotations

import sys
import os

# ---------------------------------------------------------------------------
# LeRobot 路径注入
# 优先从环境变量 LEROBOT_SRC 读取，否则使用相对路径推算
# 本文件位于：tools/ugv_data_collector/robots/
# lerobot src 位于：ref_code/lerobot-main (SmolVLA)/src
# ---------------------------------------------------------------------------
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_LEROBOT_SRC = os.environ.get("LEROBOT_SRC")

if not _LEROBOT_SRC:
    _PROJECT_ROOT = os.path.abspath(os.path.join(_CURRENT_DIR, "../../.."))
    _LEROBOT_SRC = os.path.join(_PROJECT_ROOT, "ref_code", "lerobot-main (SmolVLA)", "src")

if os.path.exists(_LEROBOT_SRC) and _LEROBOT_SRC not in sys.path:
    sys.path.insert(0, _LEROBOT_SRC)
