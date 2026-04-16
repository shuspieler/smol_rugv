#!/bin/bash
# Jetson Orin CMA 内存碎片清理
# 用途：反复加载/卸载模型后 CmaFree 下降，导致 nvmap OOM，
#       运行此脚本回收页缓存并压缩物理页，恢复 CMA 可用空间。
# 需要 sudo 权限。

set -e

# 非交互场景（如 ros2 launch）下，避免 sudo 密码提示导致阻塞。
# 规则：
# 1) root 直接执行；
# 2) 非 root 且支持 sudo -n 时使用 sudo -n；
# 3) 否则打印提示并跳过（返回 0，避免影响主流程）。
SUDO_CMD=()
if [ "$(id -u)" -eq 0 ]; then
	SUDO_CMD=()
elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
	SUDO_CMD=(sudo -n)
else
	echo "[WARN] 无法非交互执行内存整理（需要 root 或 sudo NOPASSWD）。已跳过。"
	echo "[WARN] 如需手动执行：sudo bash ./defrag_memory.sh"
	exit 0
fi

echo "=== 清理前 ==="
grep -i cma /proc/meminfo
free -h | head -2

sync
echo 3 | "${SUDO_CMD[@]}" tee /proc/sys/vm/drop_caches > /dev/null
"${SUDO_CMD[@]}" sh -c 'echo 1 > /proc/sys/vm/compact_memory'
sleep 1

echo ""
echo "=== 清理后 ==="
grep -i cma /proc/meminfo
free -h | head -2
