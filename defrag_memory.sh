#!/bin/bash
# Jetson Orin CMA 内存碎片清理
# 用途：反复加载/卸载模型后 CmaFree 下降，导致 nvmap OOM，
#       运行此脚本回收页缓存并压缩物理页，恢复 CMA 可用空间。
# 需要 sudo 权限。

set -e

echo "=== 清理前 ==="
grep -i cma /proc/meminfo
free -h | head -2

sync
echo 3 | sudo tee /proc/sys/vm/drop_caches > /dev/null
sudo sh -c 'echo 1 > /proc/sys/vm/compact_memory'
sleep 1

echo ""
echo "=== 清理后 ==="
grep -i cma /proc/meminfo
free -h | head -2
