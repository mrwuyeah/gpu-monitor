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

## 一键部署（推荐）

```bash
curl -O https://raw.githubusercontent.com/mrwuyeah/gpu-monitor/main/deploy_linux.sh
chmod +x deploy_linux.sh && ./deploy_linux.sh
```

该脚本自动完成以下步骤：

1. 安装系统依赖（python3、pip、build-essential）
2. 检查 NVIDIA 驱动与 `nvidia-smi`
3. 从 GitHub 克隆最新代码
4. 安装 Python 依赖 & PyInstaller
5. 打包为单文件可执行文件

部署完成后：

```bash
cd ~/gpu_monitor
./dist/gpu_monitor
```

浏览器打开 `http://localhost:5000` 即可访问。

---

## 分步部署（手动）

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
git clone https://github.com/mrwuyeah/gpu-monitor.git ~/gpu_monitor
cd ~/gpu_monitor
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
- 系统会依次尝试：PID 匹配 → 端口扫描 localhost:8000-8009

**Q: vLLM 显存显示 0 MB？**
确认 vLLM 的 `/metrics` 端点有 `vllm:kv_cache_usage_perc` 指标。系统使用 `总显存 × kv_usage` 推算显存占用。

**Q: 数据库写权限？**
可执行文件所在目录需要写权限（`gpu_usage.db` 创建于此）。

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `deploy_linux.sh` | 一键部署脚本（克隆 + 打包） |
| `build_linux.sh` | 打包脚本（仅打包，需已有源码） |
| `Linux部署指南.md` | 本部署文档 |
| `gpu_monitor.spec` | PyInstaller 打包配置文件 |
| `Ubuntu 24.04.4 GPU监控初始版本5.7 - 快速部署指南.pdf` | 原始版本部署手册（PDF 归档） |
