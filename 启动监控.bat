@echo off
chcp 65001 >nul
echo 正在启动GPU监控服务...
echo.
echo 请确保已安装Flask: pip install flask
echo.
python app.py
pause
