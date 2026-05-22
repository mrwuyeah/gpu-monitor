# Ubuntu 24.04.4 GPU监控可执行文件 - 快速部署指南

## 版本：2026/5/22 多VLLM进程监控版本

源码已上传GitHub：

```
git clone https://github.com/mrwuyeah/gpu-monitor.git
```

预览：

![c7aded675ca6b798186831235815ada6](C:\Users\18163\Desktop\VSCODE\gpu_win\assets\c7aded675ca6b798186831235815ada6.jpg)



### 第1步：在Ubuntu上安装依赖
```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装Python和编译工具
sudo apt install -y python3 python3-pip python3-dev build-essential

# 安装NVIDIA驱动（如果还没安装）：如果可以nvidia-smi就不用了
sudo apt install -y nvidia-driver-550
sudo apt install -y nvidia-utils

# 重启系统（安装驱动后需要）
sudo reboot
```

### 第2步：下载项目文件到Ubuntu
将整个 `gpu_win` 文件夹复制到Ubuntu，或克隆项目：
```bash
# 进入工作目录
cd /home/your-user/projects

# 创建项目目录
mkdir gpu_monitor && cd gpu_monitor

# 将以下文件复制到此目录：
# - app.py
# - build_linux.sh
# - requirements.txt
# - build_executable.spec
# - templates/ 文件夹
```

### 第3步：打包为可执行文件
```bash
# 给脚本执行权限
chmod +x build_linux.sh

# 运行打包脚本
./build_linux.sh
```

打包完成后，可执行文件位于：
```bash
dist/gpu_monitor
```

## 🚀 运行可执行文件

### 方式1：直接运行
```bash
chmod +x dist/gpu_monitor
./dist/gpu_monitor
```

### 方式2：后台运行（推荐长期监控）
```bash
# 在后台运行（默认端口5000）
nohup ./dist/gpu_monitor > gpu_monitor.log 2>&1 &

# 在后台运行（指定端口5001）
nohup ./dist/gpu_monitor --port 5001 > gpu_monitor.log 2>&1 &

# 在后台运行（指定地址和端口）
nohup ./dist/gpu_monitor --host 0.0.0.0 --port 5001 > gpu_monitor.log 2>&1 &

# 查看日志
tail -f gpu_monitor.log

# 停止运行
pkill -f gpu_monitor
```

### 方式3：使用systemd服务（开机自启）

创建服务文件：
```bash
sudo nano /etc/systemd/system/gpu-monitor.service
```

复制以下内容：
```ini
[Unit]
Description=GPU Monitor Service
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/home/your-username/projects/gpu_monitor
ExecStart=/home/your-username/projects/gpu_monitor/dist/gpu_monitor
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启用服务：
```bash
# 重新加载systemd
sudo systemctl daemon-reload

# 启用服务
sudo systemctl enable gpu-monitor.service

# 启动服务
sudo systemctl start gpu-monitor.service

# 查看服务状态
sudo systemctl status gpu-monitor.service
```

## 🌐 访问Web界面

启动后，在浏览器打开：
```
http://localhost:5000
```

### 从其他电脑访问
```bash
# 查看Ubuntu的IP地址
hostname -I

# 在其他电脑浏览器打开
http://ubuntu-ip:5000
```

历史查询：

![dea476c67cfe30d6cd0530555b902a94](C:\Users\18163\Desktop\VSCODE\gpu_win\assets\dea476c67cfe30d6cd0530555b902a94.png)

![f92e5e8fa6e18c59667143fd9a9b56f5](C:\Users\18163\Desktop\VSCODE\gpu_win\assets\f92e5e8fa6e18c59667143fd9a9b56f5.png)
