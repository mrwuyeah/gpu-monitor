#!/bin/bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_BIN="$SCRIPT_DIR/dist/gpu_monitor"
LOG_FILE="$SCRIPT_DIR/gpu_monitor_runtime.log"

echo "GPU监控启动器"
echo "程序路径: $APP_BIN"
echo "日志文件: $LOG_FILE"
echo ""

if [ ! -f "$APP_BIN" ]; then
    echo "未找到可执行文件: $APP_BIN"
    echo "请先执行 ./build_linux.sh 生成可执行文件。"
    read -r -p "按回车键退出..."
    exit 1
fi

chmod +x "$APP_BIN" 2>/dev/null || true

echo "正在启动..."
echo ""

"$APP_BIN" > "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -ne 0 ]; then
    echo "程序退出，退出码: $EXIT_CODE"
    echo "下面是最后的日志："
    echo "----------------------------------------"
    tail -n 100 "$LOG_FILE"
    echo "----------------------------------------"
    echo "请根据日志排查问题。"
else
    echo "程序已退出。"
fi

read -r -p "按回车键退出..."
exit $EXIT_CODE
