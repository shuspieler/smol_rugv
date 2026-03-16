#!/usr/bin/env bash
# serial_raw.sh — 用纯 shell 工具（stty + xxd/od）查看串口原始数据
# 不依赖任何 Python 包
#
# 用法:
#   bash serial_raw.sh [端口] [波特率] [模式]
#
# 示例:
#   bash serial_raw.sh /dev/ttyCH341USB0 115200 hex    # hex dump (默认)
#   bash serial_raw.sh /dev/ttyCH341USB0 115200 text   # 可见字符
#   bash serial_raw.sh /dev/ttyCH341USB0 115200 raw    # 直接 cat 输出到终端

PORT="${1:-/dev/ttyCH341USB0}"
BAUD="${2:-115200}"
MODE="${3:-hex}"

echo "========================================"
echo "  串口原始数据查看器 (纯 shell)"
echo "  port=$PORT  baud=$BAUD  mode=$MODE"
echo "  按 Ctrl+C 退出"
echo "========================================"
echo ""

# 检查设备是否存在
if [ ! -e "$PORT" ]; then
    echo "[错误] 设备不存在: $PORT"
    echo "可用串口设备:"
    ls /dev/ttyCH341USB* /dev/ttyUSB* /dev/ttyACM* /dev/ttyTHS* /dev/ttyS* 2>/dev/null | xargs -I{} sh -c 'echo "  {}"'
    exit 1
fi

# 检查权限
if [ ! -r "$PORT" ]; then
    echo "[错误] 无读取权限: $PORT"
    echo "尝试: sudo chmod a+rw $PORT  或  sudo usermod -aG dialout \$USER"
    exit 1
fi

# 用 stty 配置串口（raw 模式，不做任何转换）
echo "[配置] stty $PORT $BAUD raw ..."
stty -F "$PORT" "$BAUD" cs8 -cstopb -parenb raw -echo 2>&1
if [ $? -ne 0 ]; then
    echo "[错误] stty 配置失败，可能需要 sudo"
    exit 1
fi
echo "[配置] OK"
echo ""

case "$MODE" in
    hex)
        echo "[模式] HEX DUMP（每行 16 字节，实时显示）"
        echo "       全零 = 悬空/PM休眠  随机字节 = 波特率不对  有意义JSON = 正常"
        echo ""
        # xxd 优先，od 备用
        if command -v xxd &>/dev/null; then
            cat "$PORT" | xxd -cols 16
        else
            cat "$PORT" | od -A x -t x1z -v
        fi
        ;;
    text)
        echo "[模式] 文本（不可见字符显示为点）"
        echo ""
        cat "$PORT" | tr -cd '\x20-\x7e\x0a\x0d' | while IFS= read -r line; do
            echo "$(date '+%H:%M:%S.%3N')  $line"
        done
        ;;
    raw)
        echo "[模式] RAW — 直接输出到终端（可能乱码）"
        echo ""
        cat "$PORT"
        ;;
    *)
        echo "[错误] 未知模式: $MODE，可选: hex / text / raw"
        exit 1
        ;;
esac
