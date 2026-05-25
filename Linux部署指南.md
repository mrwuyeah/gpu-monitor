# GPU 监控系统 — Linux 部署指南

## 版本信息

| 项目 | 内容 |
|------|------|
| 版本 | 2026/5/22 多 vLLM 进程监控版本 |
| 目标平台 | Ubuntu 24.04+ / 其他 Linux 发行版 |
| 运行环境 | Python 3.8+，NVIDIA 驱动 + nvidia-smi |
| 打包方式 | PyInstaller `--onefile` |

### 功能概要
- GPU 实时监控（利用率、显存、温度、功耗）
- 多 vLLM 实例自动发现（原生 PID 匹配 / 端口扫描）
- vLLM Prometheus 指标聚合（KV Cache 使用率、请求数、Token 数）
- 控制台多实例管理（基于角色的权限控制）
- SQLite 持久化历史数据与趋势图表

---

## 快速部署

### 1. 安装系统依赖

```bash
sudo apt update && sudo apt install -y \
  python3 python3-pip python3-dev build-essential
```

确认 NVIDIA 驱动可用：

```bash
nvidia-smi
```

如未安装驱动：

```bash
sudo apt install -y nvidia-driver-550
sudo reboot
```

### 2. 获取项目文件

```bash
# 创建项目目录
mkdir -p ~/gpu_monitor && cd ~/gpu_monitor
```

将以下文件放置于此目录：

```
app.py
auth.py
console_routes.py
build_linux.sh
requirements.txt
templates/
├── index.html
├── history.html
├── console_login.html
├── console_index.html
├── console_settings.html
└── console_users.html
```

### 3. 打包为可执行文件

```bash
chmod +x build_linux.sh
./build_linux.sh
```

打包完成后可执行文件位于 `./dist/gpu_monitor`。

---

## 运行方式

### 前台运行

```bash
./dist/gpu_monitor
# 或指定端口
./dist/gpu_monitor --port 5001
```

### 后台运行（推荐长期监控）

```bash
nohup ./dist/gpu_monitor > gpu_monitor.log 2>&1 &
tail -f gpu_monitor.log        # 查看启动日志
pkill -f gpu_monitor           # 停止
```

### Systemd 服务（开机自启）

创建 `/etc/systemd/system/gpu-monitor.service`：

```ini
[Unit]
Description=GPU Monitor Service
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/home/your-user/gpu_monitor
ExecStart=/home/your-user/gpu_monitor/dist/gpu_monitor
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gpu-monitor.service
sudo systemctl status gpu-monitor.service
```

---

## 访问 Web 界面

| 页面 | 地址 |
|------|------|
| 实时监控 | `http://localhost:5000` |
| 历史数据 | `http://localhost:5000/history` |
| 控制台 | `http://localhost:5000/console` |

首次启动时终端会打印自动生成的 API 令牌，请及时保存。

> 控制台默认超级管理员：`yofc`，首次启动时自动创建，密码在启动日志中可见（若遗失可通过 SQLite 手动重置）。

---

## 默认用户

| 用户名 | 角色 | 说明 |
|--------|------|------|
| `yofc` | admin | 超级管理员，首次启动自动创建 |

---

## 首次启动初始化

应用首次运行时会自动完成：

1. 创建 `gpu_usage.db`（SQLite 数据库及全部表结构）
2. 创建默认超级管理员 `yofc`
3. 生成随机 API 令牌（打印在终端）
4. 生成持久化 Session 密钥

---

## 打包说明

`build_linux.sh` 使用 PyInstaller 打包为单文件可执行文件，关键参数：

| 参数 | 值 | 说明 |
|------|-----|------|
| `--onefile` | — | 打包为单个可执行文件 |
| `--console` | — | 带控制台窗口（可查看日志） |
| `--add-data` | `templates:templates` | 嵌入 HTML 模板 |
| `--name` | `gpu_monitor` | 输出文件名 |

隐式导入模块确保打包包含动态加载的依赖：

```
flask, werkzeug, jinja2, itsdangerous, click, markupsafe,
psutil, auth, console_routes
```

---

## 常见问题

**Q: 启动后无法打开页面？**
检查日志：`cat gpu_monitor.log` 或 `journalctl -u gpu-monitor.service`。

**Q: 找不到模板文件？**
确认 `templates/` 目录与可执行文件在同一位置，或已通过 `--add-data` 打包进可执行文件。

**Q: nvidia-smi 不可用？**
确认 NVIDIA 驱动已安装：`nvidia-smi` 应正常输出 GPU 信息。

**Q: 检测不到 vLLM 进程？**
- 确认 vLLM 已启动且 nvidia-smi 可查询到其计算进程
- 确认 vLLM 的 Prometheus 端点（`/metrics`）可访问
- 系统会依次尝试：PID 匹配 → WSL 探测 → localhost:8000-8009 端口扫描

**Q: vLLM 显存显示 0 MB？**
确认 vLLM 的 `/metrics` 端点有 `vllm:kv_cache_usage_perc` 指标。系统使用 `总显存 × kv_usage` 推算显存占用。

**Q: 数据库写权限？**
可执行文件所在目录需要写权限（`gpu_usage.db` 创建于此）。

---

## 预览

![GPU 监控面板](assets/50a9184822762131e78611d375b1ca17.png)

![历史查询](assets/dea476c67cfe30d6cd0530555b902a94.png)
