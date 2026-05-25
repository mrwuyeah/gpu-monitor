@echo off
chcp 65001 >nul
setlocal

cd /d %~dp0

echo ========================================
echo GPU监控应用打包工具 - Windows版本
echo ========================================
echo.

REM 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未检测到Python，请先安装Python 3.6+
    pause
    exit /b 1
)

echo [1/4] 正在检查依赖...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [1/4] 依赖安装失败
    pause
    exit /b 1
)

python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [2/4] 正在安装PyInstaller...
    python -m pip install pyinstaller
) else (
    echo [2/4] PyInstaller已安装
)

echo.
echo [3/4] 正在清理旧的构建文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist gpu_monitor.spec del gpu_monitor.spec

echo.
echo [4/4] 正在打包应用...
echo 这个过程可能需要1-2分钟，请耐心等待...
echo.

python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --console ^
    --name gpu_monitor ^
    --add-data "templates;templates" ^
    --hidden-import flask ^
    --hidden-import werkzeug ^
    --hidden-import jinja2 ^
    --hidden-import itsdangerous ^
    --hidden-import click ^
    --hidden-import markupsafe ^
    --hidden-import psutil ^
    --exclude PyQt5 ^
    --exclude PySide6 ^
    --exclude matplotlib ^
    --exclude IPython ^
    --exclude sphinx ^
    --exclude jedi ^
    --exclude black ^
    --exclude nbformat ^
    --exclude zmq ^
    app.py

if errorlevel 1 (
    echo.
    echo 错误: 打包失败！
    pause
    exit /b 1
)

echo.
echo ========================================
echo ✓ 打包完成！
echo ========================================
echo.
echo 可执行文件位置: dist\gpu_monitor.exe
echo.
echo 使用方法:
echo 1. 打开命令行
echo 2. 运行: dist\gpu_monitor.exe
echo 3. 在浏览器打开: http://localhost:5000
echo.
echo 首次运行会自动生成默认 API 令牌，请在终端查看并保存。
echo.
pause
endlocal
