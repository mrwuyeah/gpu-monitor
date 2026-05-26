#!/bin/bash

# GPU监控应用打包工具 - Ubuntu/Linux版本

set -e  # 错误时退出

echo "========================================"
echo "GPU监控应用打包工具 - Linux版本"
echo "========================================"
echo ""

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "错误: 未检测到Python3，请先安装: sudo apt install python3 python3-pip"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "[1/5] Python版本: $PYTHON_VERSION"
echo ""

# 检查并安装依赖
echo "[2/5] 安装Python依赖..."
python3 -m pip install -r requirements.txt

echo "[2/5] 检查PyInstaller..."
if ! python3 -m pip show pyinstaller &> /dev/null; then
    echo "[2/5] 正在安装PyInstaller..."
    python3 -m pip install pyinstaller
else
    echo "[2/5] PyInstaller已安装"
fi

echo ""
echo "[3/5] 清理旧的构建文件..."
rm -rf build/ dist/ gpu_monitor.spec 2>/dev/null || true

echo ""
echo "[4/5] 正在打包应用..."
echo "这个过程可能需要2-3分钟，请耐心等待..."
echo ""

python3 -m PyInstaller \
    --noconfirm \
    --clean \
    --onefile \
    --console \
    --add-data "templates:templates" \
    --hidden-import=flask \
    --hidden-import=werkzeug \
    --hidden-import=jinja2 \
    --hidden-import=itsdangerous \
    --hidden-import=click \
    --hidden-import=markupsafe \
    --hidden-import=psutil \
    --hidden-import=auth \
    --hidden-import=console_routes \
    --hidden-import=pymysql \
    --name gpu_monitor \
    app.py

if [ $? -ne 0 ]; then
    echo ""
    echo "错误: 打包失败！"
    exit 1
fi

echo ""
echo "========================================"
echo "✓ 打包完成！"
echo "========================================"
echo ""
echo "可执行文件位置: ./dist/gpu_monitor"
echo ""
echo "使用方法:"
echo "1. 打开终端"
echo "2. 运行: ./dist/gpu_monitor"
echo "3. 在浏览器打开: http://localhost:5000"
echo ""
echo "或者设置权限后直接运行:"
echo "chmod +x dist/gpu_monitor"
echo "./dist/gpu_monitor"
echo ""
