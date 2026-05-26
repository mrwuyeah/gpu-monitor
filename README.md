# GPU 实时监控系统

## 一、简介

这是一套 GPU 集群监控工具，用于实时查看 NVIDIA GPU 运行状态、自动发现 vLLM 推理进程并聚合指标（KV Cache 使用率、请求数等），支持多台服务器统一管理、历史数据回溯与角色权限控制。提供 Web 界面与 RESTful API，可打包为 Windows / Linux 独立可执行文件。

---

## 二、界面一览

**2.1 控制台 — 登录与实例管理**

登录后进入控制台，可添加多台 GPU 服务器的监控实例（名称 + Base URL + API 令牌），统一管理所有 GPU 节点。实例支持三级角色权限（管理员 / 高级 / 初级），可指定哪些角色能访问。

<img src="c41c989441e59182afe4680d0cfb089d.png" width="750" alt="控制台 — 实例管理" />

---

**2.2 控制台 — API 令牌与密码**

每个 GPU 监控服务启动时自动生成唯一的 API 令牌。在控制台可查看、复制、重新生成令牌。其他服务器要接入此服务时需提供该令牌。同时支持登录用户修改自身密码。

<img src="d1013faf5c7644ff41041cf9993dccd7.png" width="750" alt="API 令牌设置" />

---

**2.3 实时监控面板**

以卡片形式展示每张 GPU 的实时状态：利用率、显存占用（总量 / 已用）、温度、功耗。下方表格列出该 GPU 上检测到的 vLLM 进程，显示 PID、模型名称、显存占用、KV Cache 使用率、运行中 / 排队中请求数等指标。支持一键跳转历史查询。

<img src="2e994f6c3e0935b8dc04dbc6905dcbd7.png" width="750" alt="实时监控面板" />

---

**2.4 控制台 — 用户管理**

超级管理员可创建 / 删除用户，分配角色（高级 / 初级），控制不同用户的实例访问权限。

<img src="eb2c97a6766ecea13c106b319066963b.jpg" width="750" alt="用户管理后台" />



<img src="f51987c9cfe4f4381e21147177031047.png" width="750" alt="用户管理" />

---

## 三、功能特性

#### 3.1 GPU 实时监控
- 调用 `nvidia-smi` 轮询采集每张 GPU 的利用率、显存占用、温度、功耗
- 同时采集系统 CPU 使用率
- 10 秒采样周期，内存保留最近 1 小时（360 条）实时数据
- 每 10 秒持久化到 SQLite，支持按时间范围回溯查询
---

#### 3.2 vLLM 进程自动发现
- **原生进程匹配**：通过 `nvidia-smi --query-compute-apps` 获取 GPU 上运行的 vLLM PID；当 compute-apps 接口为空时，回退为 `psutil` 扫描所有进程中的 vLLM 实例
- **跨卡进程识别**：自动检测占用多张 GPU 的 vLLM 实例（如张量并行），为每张 GPU 生成独立指标副本
- **WSL 互操作**：从 Windows 环境通过 `wsl.exe ps aux` 查询 WSL2 内运行的 vLLM 进程，提取真实 PID 与端口
- **端口扫描回退**：上述方式未发现时，自动扫描 `localhost:8000-8009` 尝试连接 vLLM Prometheus 端点
- **远程实例采集**：支持从控制台录入的远程 / 容器化 vLLM 实例采集指标

---

#### 3.3 vLLM 指标采集

- 从 vLLM Prometheus 端点（`/metrics`）提取：
  - KV Cache 使用率（`kv_cache_usage_perc`），据此推算进程显存占用：`总显存 × kv_usage`
  - 当前运行中 / 等待中的请求数
  - 累计请求总数、Prompt / Generation token 数
  - Prefix Cache 命中率
- 所有指标均以 metrics_url 为键缓存，避免重复请求
---

#### 3.4 历史数据与图表
- SQLite 持久化，支持按时间范围、GPU 索引筛选
- 分页查询表格数据（每页最大 100 条）
- 均匀采样的趋势图表（Chart.js），可切换显存占用 / GPU 利用率视图
- 快捷时间范围：最近 1 小时 / 24 小时 / 7 天
- 显存利用率 ≥ 90% 时自动记录告警

---

#### 3.5 控制台（Console）

| 功能 | 说明 |
|------|------|
| 实例管理 | 新增 / 编辑 / 删除远程监控实例，配置名称、Base URL、API 令牌、权限角色、备注 |
| 令牌验证 | 新增实例时可验证目标实例的 API 令牌是否有效 |
| 权限控制 | 三级角色：`admin` / `senior` / `junior`，实例可设置允许访问的角色 |
| 用户管理 | admin 可创建 / 删除 / 修改角色（senior / junior） |
| API 令牌管理 | 查看、复制、重新生成 API 令牌 |
| 密码修改 | 登录用户可修改自身密码 |

#### 3.6 认证与安全
- **API 认证**：`Authorization: Bearer <token>` 或 `?token=<token>`，覆盖所有 `/api/*` 路由
- **Session 认证**：Web 控制台使用 Flask Session 登录
- **双通道隔离**：Session 登录不自动获得 API 访问权限，API 令牌不暴露在 Session 中
- 默认超级管理员：`yofc`
- 首次启动自动生成随机 API 令牌与控制台 Session 密钥
---

## 四、部署
- PyInstaller 打包为 `--onefile` 可执行文件（Windows / Linux 均可）
- 监听地址 / 端口可通过 CLI 参数 `--host` / `--port` 配置
- 日志自动写入 `gpu_monitor_error.log`

---

### （1）快速开始

##### 4.1 环境要求

- Python 3.8+
- NVIDIA GPU + nvidia-smi 驱动
- Windows / Linux / WSL2

从**源码运行**

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
python app.py --host 0.0.0.0 --port 5000

# 3. 浏览器打开
#    实时监控: http://localhost:5000
#    控制台:   http://localhost:5000/console
```

首次启动会自动完成以下初始化：
- 创建 `gpu_usage.db` 数据库及所有表结构
- 生成默认超级管理员 `yofc`
- 生成随机 API 令牌（打印在终端）
- 生成持久化的 Session 密钥

**CLI 参数**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `0.0.0.0` | 监听地址 |
| `--port` | `5000` | 监听端口 |

---

### （2） 打包部署

##### 4.2 Windows

```powershell
build_windows.bat
```

##### 4.3 Linux

```bash
# 一键部署（克隆 + 打包）
curl -O https://raw.githubusercontent.com/mrwuyeah/gpu-monitor/main/deploy_linux.sh
chmod +x deploy_linux.sh && ./deploy_linux.sh

# 或手动打包
chmod +x build_linux.sh && ./build_linux.sh
```

详细步骤见 [Linux部署指南](Linux部署指南.md)。

> **注意**：Windows 打包使用 `;` 分隔 `--add-data` 路径；Linux / macOS 使用 `:`。

---

### （3）API 文档

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

`/api/gpu-info` 响应示例

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

## 五、项目结构

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
├── build_linux.sh              # Linux 打包脚本
├── deploy_linux.sh             # Linux 一键部署脚本
└── requirements.txt            # Python 依赖
```

---

## 六、数据流架构

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

## 七、数据库结构

| 表名 | 用途 | 关键列 |
|------|------|--------|
| `samples` | GPU 采样历史（10s 粒度） | `ts`, `gpu_index`, `gpu_util`, `mem_used`, `mem_total`, `temp`, `power` |
| `alerts` | 高显存利用率告警 | `ts`, `gpu_index`, `gpu_util` |
| `console_users` | 控制台用户 | `username`, `password_hash`, `role` (admin/senior/junior) |
| `monitor_instances` | 远程监控实例配置 | `name`, `base_url`, `token`, `allowed_roles` |
| `api_settings` | API 令牌 & Session 密钥 | `key-value` 存储 |
