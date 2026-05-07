@echo off
chcp 65001 >nul
setlocal

cd /d %~dp0

set EXE=dist\gpu_monitor.exe
set LOG_FILE=gpu_monitor_runtime.log

echo GPU监控启动器
echo 程序路径: %EXE%
echo 日志文件: %LOG_FILE%
echo.

if not exist %EXE% (
    echo 未找到可执行文件: %EXE%
    echo 请先运行 build_windows.bat 进行打包。
    pause
    exit /b 1
)

echo 正在启动...
echo.

%EXE% > %LOG_FILE% 2>&1
set EXIT_CODE=%ERRORLEVEL%

echo.
if not "%EXIT_CODE%"=="0" (
    echo 程序退出，退出码: %EXIT_CODE%
    echo 下面是最后的日志：
    echo ----------------------------------------
    type %LOG_FILE%
    echo ----------------------------------------
) else (
    echo 程序已退出。
)

pause
exit /b %EXIT_CODE%