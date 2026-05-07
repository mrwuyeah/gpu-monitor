# PowerShell启动脚本
Write-Host "正在启动GPU监控服务..." -ForegroundColor Green
Write-Host ""
Write-Host "请确保已安装Flask: pip install flask" -ForegroundColor Yellow
Write-Host ""
Write-Host "浏览器打开: http://localhost:5000" -ForegroundColor Cyan
Write-Host ""

python app.py

Write-Host "服务已停止" -ForegroundColor Red
