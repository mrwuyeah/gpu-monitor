#!/bin/bash
# GPU 监控系统 — Linux 一键部署脚本
# 用法: chmod +x deploy_linux.sh && ./deploy_linux.sh

set -e

GIT_REPO="https://github.com/mrwuyeah/gpu-monitor.git"
INSTALL_DIR="${HOME}/gpu_monitor"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}   $1"; }
err()   { echo -e "${RED}[ERR]${NC}  $1"; }

echo "============================================"
echo "  GPU 监控系统 — Linux 一键部署"
echo "============================================"
echo ""

# ── 1. 系统依赖 ──
info "检查系统依赖..."
OS_ID=$(grep -oP '(?<=^ID=).+' /etc/os-release 2>/dev/null || echo "unknown")
if [[ "$OS_ID" == "ubuntu" || "$OS_ID" == "debian" ]]; then
    sudo apt update && sudo apt install -y python3 python3-pip python3-dev build-essential
    ok "系统依赖已安装"
else
    info "非 Ubuntu/Debian 系统，请自行确保 python3 + pip 已安装"
fi

# ── 2. nvidia-smi 检查 ──
if command -v nvidia-smi &>/dev/null; then
    ok "nvidia-smi 可用"
else
    info "nvidia-smi 不可用，请安装 NVIDIA 驱动："
    info "  sudo apt install -y nvidia-driver-550 && sudo reboot"
fi

# ── 3. 克隆 / 更新代码 ──
if [ -d "$INSTALL_DIR" ]; then
    info "目录已存在，拉取最新代码..."
    cd "$INSTALL_DIR" && git pull
    ok "代码已更新"
else
    info "克隆代码到 $INSTALL_DIR ..."
    git clone "$GIT_REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    ok "代码已克隆"
fi

# ── 4. 安装 Python 依赖 ──
info "安装 Python 依赖..."
python3 -m pip install -r requirements.txt
ok "Python 依赖已安装"

# ── 5. 打包 ──
if ! python3 -m pip show pyinstaller &>/dev/null; then
    info "安装 PyInstaller..."
    python3 -m pip install pyinstaller
fi

info "正在打包为可执行文件（约 2-3 分钟）..."
rm -rf build/ dist/ gpu_monitor.spec 2>/dev/null || true
python3 -m PyInstaller \
    --noconfirm --clean --onefile --console \
    --add-data "templates:templates" \
    --hidden-import=flask --hidden-import=werkzeug \
    --hidden-import=jinja2 --hidden-import=itsdangerous \
    --hidden-import=click --hidden-import=markupsafe \
    --hidden-import=psutil --hidden-import=auth \
    --hidden-import=console_routes \
    --name gpu_monitor app.py

ok "打包完成！可执行文件: ${INSTALL_DIR}/dist/gpu_monitor"

echo ""
echo "============================================"
echo "  部署完成"
echo "============================================"
echo ""
echo "  运行方式："
echo "    cd ${INSTALL_DIR}"
echo "    ./dist/gpu_monitor"
echo ""
echo "  浏览器访问："
echo "    http://localhost:5000"
echo "    http://localhost:5000/console"
echo ""
