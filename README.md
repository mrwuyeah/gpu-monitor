# GPU 实时监控系统

## 概述

基于 Flask 的 GPU 监控系统，支持 NVIDIA GPU 实时状态采集、vLLM 推理进程自动发现与指标聚合、历史数据持久化查询，以及多实例控制台管理。提供 RESTful API 与 Web 双通道访问，通过 PyInstaller 打包为 Windows 独立可执行文件。

---

## 功能特性

### GPU 实时监控
- 调用 `nvidia-smi` 轮询采集每张 GPU 的利用率、显存占用、温度、功耗
- 同时采集系统 CPU 使用率
- 10 秒采样周期，内存保留最近 1 小时（360 条）实时数据
- 每 10 秒持久化到 SQLite，支持按时间范围回溯查询

### vLLM 进程自动发现
- **原生进程匹配**：通过 `nvidia-smi --query-compute-apps` 获取 GPU 上运行的 vLLM PID；当 compute-apps 接口为空时，回退为 `psutil` 扫描所有进程中的 vLLM 实例
- **跨卡进程识别**：自动检测占用多张 GPU 的 vLLM 实例（如张量并行），为每张 GPU 生成独立指标副本
- **WSL 互操作**：从 Windows 环境通过 `wsl.exe ps aux` 查询 WSL2 内运行的 vLLM 进程，提取真实 PID 与端口
- **端口扫描回退**：WSL 探测失败时，自动扫描 `localhost:8000-8009` 发现 vLLM Prometheus 端点
- **远程实例采集**：支持从控制台录入的远程 / 容器化 vLLM 实例采集指标

### vLLM 指标采集
- 从 vLLM Prometheus 端点（`/metrics`）提取：
  - KV Cache 使用率（`kv_cache_usage_perc`），据此推算进程显存占用：`总显存 × kv_usage`
  - 当前运行中 / 等待中的请求数
  - 累计请求总数、Prompt / Generation token 数
  - Prefix Cache 命中率
- 所有指标均以 metrics_url 为键缓存，避免重复请求

### 历史数据与图表
- SQLite 持久化，支持按时间范围、GPU 索引筛选
- 分页查询表格数据（每页最大 100 条）
- 均匀采样的趋势图表（Chart.js），可切换显存占用 / GPU 利用率视图
- 快捷时间范围：最近 1 小时 / 24 小时 / 7 天
- 显存利用率 ≥ 90% 时自动记录告警

### 控制台（Console）

| 功能 | 说明 |
|------|------|
| 实例管理 | 新增 / 编辑 / 删除远程监控实例，配置名称、Base URL、API 令牌、权限角色、备注 |
| 令牌验证 | 新增实例时可验证目标实例的 API 令牌是否有效 |
| 权限控制 | 三级角色：`admin` / `senior` / `junior`，实例可设置允许访问的角色 |
| 用户管理 | admin 可创建 / 删除 / 修改角色（senior / junior） |
| API 令牌管理 | 查看、复制、重新生成 API 令牌 |
| 密码修改 | 登录用户可修改自身密码 |

### 认证与安全
- **API 认证**：`Authorization: Bearer <token>` 或 `?token=<token>`，覆盖所有 `/api/*` 路由
- **Session 认证**：Web 控制台使用 Flask Session 登录
- **双通道隔离**：Session 登录不自动获得 API 访问权限，API 令牌不暴露在 Session 中
- 默认超级管理员：`yofc`
- 首次启动自动生成随机 API 令牌与控制台 Session 密钥

### 部署
- PyInstaller 打包为 `--onefile` Windows 可执行文件
- 监听地址 / 端口可通过 CLI 参数 `--host` / `--port` 配置
- 日志自动写入 `gpu_monitor_error.log`

---

## 项目结构

```
├── app.py                      # Flask 主应用入口
│   ├── 数据采集层
│   │   ├── get_gpu_info()          # nvidia-smi 解析
│   │   ├── get_vllm_processes_by_gpu()  # vLLM 发现总入口
│   │   └── monitor_gpu()           # 10s 轮询 + 持久化线程
│   │
│   ├── vLLM 探测层
│   │   ├── _fetch_vllm_metrics()         # Prometheus 端点采集
│   │   ├── _wsl_find_vllm_processes()    # WSL 进程扫描
│   │   ├── _find_vllm_port()             # 从 cmdline 提取端口
│   │   ├── _extract_model_from_cmdline() # 从 cmdline 提取模型名
│   │   └── _is_vllm_process()            # vLLM 进程判定
│   │
│   ├── API 路由 (/api/*)
│   │   ├── /api/gpu-info           # 当前 GPU 实时数据
│   │   ├── /api/gpu-history        # 最近 1 小时历史
│   │   ├── /api/query-history      # 分页历史查询
│   │   ├── /api/query-history-chart # 均匀采样图表数据
│   │   └── /api/alerts             # 告警记录
│   │
│   └── 页面路由
│       ├── /                   # 实时监控页
│       ├── /history            # 历史数据页
│       └── /console-root       # 控制台入口重定向
│
├── auth.py                     # 认证层
│   ├── api_token_required()    # API Bearer Token 验证装饰器
│   ├── login_required()        # Session 登录验证装饰器
│   ├── admin_required()        # 角色校验装饰器
│   ├── get_api_token()         # 读取当前 API 令牌
│   └── role_at_least() / can_access_instance()  # 权限辅助
│
├── console_routes.py           # 控制台蓝本 (/console)
│   ├── 登录/登出
│   ├── 实例 CRUD + 令牌验证
│   ├── 用户 CRUD + 角色修改
│   ├── API 令牌查看/重新生成
│   └── 密码修改
│
├── templates/
│   ├── index.html              # 实时监控主页
│   ├── history.html            # 历史数据查询页
│   ├── console_login.html      # 控制台登录页
│   ├── console_index.html      # 控制台实例管理
│   ├── console_settings.html   # API 令牌与密码设置
│   └── console_users.html      # 用户管理
│
├── gpu_monitor.spec            # PyInstaller 打包配置
├── build_windows.bat           # Windows 打包脚本
└── requirements.txt            # Python 依赖
```

---

## 数据流架构

```
nvidia-smi ──┬──> get_gpu_info() ──┐
             │                      ├──> monitor_gpu() ──┬──> current_gpu_data (内存)
             │                      │                      └──> samples 表 (SQLite)
             │                      │
vLLM         │                      │
  ├─ PID 匹配 ──> compute-apps ──┐  │
  ├─ WSL 探测 ──> wsl.exe aux  ──┤  ├──> get_vllm_processes_by_gpu()
  ├─ 端口扫描 ──> localhost:800X  ┘  │
  └─ 远程实例 ──> HTTP Prometheus ──┘
                                      │
HTTP API  <── api_token_required <───┘
Web 页面  <── session auth <───┘
                                      │
控制台 <── login_required ────────────┘
```

---

## 安装与运行

### 环境要求

- Python 3.8+
- NVIDIA GPU + nvidia-smi 驱动
- Windows / Linux（WSL2 需安装 `wsl.exe`）

### 部署步骤

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务（开发模式）
python app.py --host 0.0.0.0 --port 5000

# 3. 打开浏览器
#    实时监控: http://localhost:5000
#    控制台:   http://localhost:5000/console
```

首次启动会自动完成以下初始化：
- 创建 `gpu_usage.db` 数据库及所有表结构
- 生成默认超级管理员 `yofc`
- 生成随机 API 令牌（打印在终端）
- 生成持久化的 Session 密钥

### CLI 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `0.0.0.0` | 监听地址 |
| `--port` | `5000` | 监听端口 |

### 打包为可执行文件

**Windows：**

```powershell
# 直接运行打包脚本
build_windows.bat
```

**Linux：**

```bash
# 直接运行打包脚本
chmod +x build_linux.sh && ./build_linux.sh
```

详细步骤见 [Linux部署指南](Linux部署指南.md)。

> **注意**：Windows 打包使用 `;` 分隔 `--add-data` 路径；Linux / macOS 使用 `:`。

---

## API 文档

所有 API 路由需携带令牌访问，支持两种方式：

```
Authorization: Bearer <token>
?token=<token>
```

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/gpu-info` | GET | 当前 GPU 实时数据（包含 vLLM 进程信息） |
| `/api/gpu-history` | GET | 最近 1 小时历史数据（360 条，内存队列） |
| `/api/query-history` | GET | 分页历史查询（参数：`start`、`end`、`gpu`、`page`、`page_size`） |
| `/api/query-history-chart` | GET | 均匀采样图表数据（参数：`start`、`end`、`gpu`、`sample_size`） |
| `/api/alerts` | GET | 告警记录（参数：`limit`） |

### `/api/gpu-info` 响应示例

```json
{
  "timestamp": "2026-05-25 14:30:00",
  "cpu_util": 45.2,
  "gpus": [
    {
      "index": 0,
      "name": "NVIDIA A100 80GB",
      "gpu_util": 78.5,
      "mem_util": 62.3,
      "mem_used": 49800.0,
      "mem_total": 81280.0,
      "temp": 65.0,
      "power": 285.0,
      "vllm_processes": [
        {
          "pid": 12345,
          "name": "vLLM (WSL)",
          "model_name": "/models/Qwen2.5-72B",
          "used_memory_mb": 65024.0,
          "kv_usage": 0.8,
          "running": 12,
          "waiting": 3,
          "gpu_indices": [0, 1, 2, 3],
          "is_cross_gpu": true
        }
      ]
    }
  ]
}
```

---

## 数据库结构

| 表名 | 用途 | 关键列 |
|------|------|--------|
| `samples` | GPU 采样历史（10s 粒度） | `ts`, `gpu_index`, `gpu_util`, `mem_used`, `mem_total`, `temp`, `power` |
| `alerts` | 高显存利用率告警 | `ts`, `gpu_index`, `gpu_util` |
| `console_users` | 控制台用户 | `username`, `password_hash`, `role` (admin/senior/junior) |
| `monitor_instances` | 远程监控实例配置 | `name`, `base_url`, `token`, `allowed_roles` |
| `api_settings` | API 令牌 & Session 密钥 | `key-value` 存储 |
