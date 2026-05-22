# Ubuntu 24.04.4 GPU监控可执行文件 - 快速部署指南

## 版本

**2026/5/22 多VLLM进程监控版本**

- 多 VLLM 实例监控（不同端口自动发现）
- 跨卡/单卡进程识别与展示
- vLLM Metrics 汇总聚合（运行中/排队中/KV缓存/Token统计）
- 多实例控制台管理（添加/编辑/删除监控实例）
- 历史数据查询与图表趋势

## 📋 3步快速部署

源码已上传GitHub：

```
git clone https://github.com/mrwuyeah/gpu-monitor.git
```

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

### 方式4：指定端口多实例运行
```bash
# 默认端口5000
./dist/gpu_monitor

# 自定义端口
./dist/gpu_monitor --port 5001
```

## 🌐 访问Web界面

启动后，在浏览器打开：
```
http://localhost:5000
```

### 控制台管理
```
http://localhost:5000/console
```
默认账号/密码：admin / admin

支持添加多个 GPU 监控实例地址，统一管理。

### 从其他电脑访问
```bash
# 查看Ubuntu的IP地址
hostname -I

# 在其他电脑浏览器打开
http://ubuntu-ip:5000
```

## 主要功能

| 功能 | 说明 |
|------|------|
| GPU实时监控 | 计算使用率、显存、温度、功耗 |
| vLLM进程监控 | 自动发现 vLLM 实例，显示运行中/排队中/KV缓存 |
| 多端口支持 | 同时监控多个不同端口的 vLLM 实例 |
| 跨卡识别 | 自动标记跨多张 GPU 的进程 |
| 历史查询 | 趋势图表展示，支持按时间/GPU筛选 |
| 控制台 | 多实例统一管理入口 |
| 告警 | 显存使用率超过90%自动告警 |

## ✅ 打包前的准备（必要）

在开始打包前，建议在 Ubuntu 环境执行以下准备，以保证生成的可执行文件可正常访问 GPU 和模板文件：

```bash
# 确保已安装 Python + pip
sudo apt update && sudo apt install -y python3 python3-pip build-essential

# 安装项目依赖（在项目根目录）
python3 -m pip install -r requirements.txt

# 安装 PyInstaller（如果 build_linux.sh 没有安装）
python3 -m pip install pyinstaller

# 确认 nvidia-smi 可用（运行时需要）
nvidia-smi
```

说明：可执行文件应在与打包时相同的目标架构与系统上构建（在目标 Ubuntu 机器或相同版本的容器/VM 上打包更可靠）。

## 🛠 常见问题与排查

- 如果启动后无法打开页面：检查 `gpu_monitor.log`（如果用 `nohup`），或查看 `journalctl -u gpu-monitor.service`（若用了 systemd）。
- 如果提示找不到模板或静态文件，确认 `templates/` 文件夹已随可执行文件一起打包（`build_linux.sh` 会通过 PyInstaller 的 `--add-data "templates:templates"` 添加）。
- 如果程序无法读取 GPU 数据，确认 `nvidia-smi` 在 PATH 中且 NVIDIA 驱动已正确安装。
- 如果要在后台长期运行并记录数据，请确保可执行文件所在目录具有写权限（sqlite 数据库 `gpu_usage.db` 将写在当前工作目录）。
- 如果页面显示"未检测到 vLLM 进程"，确认 vLLM 已启动并且 nvidia-smi 可以查询到其计算进程。
- 如果 vLLM 指标显示 `-`，系统无法连接到 vLLM 的 `/metrics` 接口，确认端口是否正确。

预览：

![c7aded675ca6b798186831235815ada6](C:\Users\18163\Desktop\VSCODE\gpu_win\assets\c7aded675ca6b798186831235815ada6.jpg)

历史查询：

![dea476c67cfe30d6cd0530555b902a94](C:\Users\18163\Desktop\VSCODE\gpu_win\assets\dea476c67cfe30d6cd0530555b902a94.png)

![f92e5e8fa6e18c59667143fd9a9b56f5](C:\Users\18163\Desktop\VSCODE\gpu_win\assets\f92e5e8fa6e18c59667143fd9a9b56f5.png)
