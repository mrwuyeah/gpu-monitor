# DBeaver 连接 MySQL 配置指南

> 适用场景：从本地 SQLite 迁移到公司内网 MySQL 数据库（10.99.19.243:3306）

---

## 1. 在 DBeaver 中新建连接

### 1.1 打开新建连接向导

- DBeaver → 菜单栏 **数据库** → **新建数据库连接**
- 或点击左上角「插头+」图标

### 1.2 选择 MySQL 驱动

- 在搜索框输入 `MySQL`
- 选择 **MySQL**（一般选第二个，带 `8.x` 或 `Tunnel` 的那个）
- 点击 **下一步**

### 1.3 填写连接参数

| 参数 | 值 |
|------|------|
| **主机 (Host)** | `10.99.19.243` |
| **端口 (Port)** | `3306` |
| **数据库 (Database)** | `gpu_monitor`（如不存在，可先填 `mysql`，后面再创建） |
| **用户名 (Username)** | `model-monitor` |
| **密码 (Password)** | `iVDbNxcRAU1A/CcD` |

> **注意**：凭据 `model-monitor/iVDbNxcRAU1A/CcD` 的格式暂未确认。如果上述用户名/密码连不上，尝试：
> - 用户: `model-monitor`  密码: `iVDbNxcRAU1A/CcD`
> - 或询问 DBA 确认正确的用户名和密码

### 1.4 驱动设置

- 如果提示 "下载驱动"，点击下载并安装 MySQL 驱动包
- 在 **驱动属性** 中，建议设置：
  - `allowPublicKeyRetrieval` = `true`
  - `useSSL` = `false`（内网环境通常不需要）

### 1.5 测试连接

- 点击 **测试连接 (Test Connection)**
- 如果出现绿色勾 ✓，说明连接成功
- 如果失败，检查网络连通性：`ping 10.99.19.243`、`telnet 10.99.19.243 3306`

---

## 2. 创建数据库和表

### 2.1 创建数据库

连接成功后，在 DBeaver 中新建一个数据库：

```sql
CREATE DATABASE IF NOT EXISTS gpu_monitor
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_general_ci;
```

创建后，右键左侧导航栏 → **刷新**，即可看到 `gpu_monitor` 库。

---

### 2.2 创建数据表

切换到 `gpu_monitor` 数据库，打开 SQL 编辑器（右键库 → **SQL 编辑器**），依次执行：

```sql
-- samples：GPU 采样历史（10 秒粒度）
CREATE TABLE IF NOT EXISTS samples (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ts VARCHAR(255),
    cpu_util DOUBLE,
    gpu_index INT,
    name TEXT,
    gpu_util DOUBLE,
    mem_util DOUBLE,
    mem_used DOUBLE,
    mem_total DOUBLE,
    temp DOUBLE,
    power DOUBLE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- alerts：高显存利用率告警
CREATE TABLE IF NOT EXISTS alerts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ts VARCHAR(255),
    gpu_index INT,
    gpu_util DOUBLE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- console_users：控制台用户
CREATE TABLE IF NOT EXISTS console_users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'user',
    created_at VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- monitor_instances：远程监控实例配置
CREATE TABLE IF NOT EXISTS monitor_instances (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    base_url TEXT NOT NULL,
    metrics_url TEXT,
    notes TEXT,
    token TEXT DEFAULT '',
    allowed_roles TEXT DEFAULT 'admin,senior,junior',
    created_at VARCHAR(255),
    updated_at VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- api_settings：API 令牌 & Session 密钥
CREATE TABLE IF NOT EXISTS api_settings (
    `key` VARCHAR(255) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

执行后，左侧导航栏展开 `gpu_monitor` → **表** 即可看到全部 5 张表。

> **替代方案**：以上建表 SQL 仅供参考——生产环境中可直接启动 app.py，`init_db()` 函数会自动检测并创建缺失的表。

---

## 3. 配置环境变量并启动应用

在运行 `app.py` 之前，设置以下环境变量，让应用连接到 MySQL 而非 SQLite：

### Windows（CMD）

```cmd
set DB_HOST=10.99.19.243
set DB_PORT=3306
set DB_USER=model-monitor
set DB_PASSWORD=iVDbNxcRAU1A/CcD
set DB_NAME=gpu_monitor
python app.py
```

### Windows（PowerShell）

```powershell
$env:DB_HOST="10.99.19.243"
$env:DB_PORT="3306"
$env:DB_USER="model-monitor"
$env:DB_PASSWORD="iVDbNxcRAU1A/CcD"
$env:DB_NAME="gpu_monitor"
python app.py
```

### Linux / macOS

```bash
export DB_HOST=10.99.19.243
export DB_PORT=3306
export DB_USER=model-monitor
export DB_PASSWORD='iVDbNxcRAU1A/CcD'
export DB_NAME=gpu_monitor
python3 app.py
```

### 不设置环境变量（本地开发）

如果不设置任何环境变量，默认连接 `localhost:3306`，用户 `root`，密码空，库名 `gpu_monitor`。适合本地开发测试。

---

## 4. 验证连接成功

启动应用后，观察终端输出：

- 不报错且显示 `GPU监控服务启动中...` → 连接成功
- 如果报错 `Can't connect to MySQL server` 或 `Access denied` → 检查用户名密码、网络连通性
- 如果报 `Unknown database 'gpu_monitor'` → 先用 DBeaver 执行 `CREATE DATABASE gpu_monitor;`

---

## 5. 常见问题

| 问题 | 解决方法 |
|------|----------|
| `Access denied for user` | 确认用户名/密码正确 |
| `Unknown database` | 用 DBeaver 先创建 `gpu_monitor` 库 |
| `Can't connect to MySQL` | 检查 IP/端口是否正确、网络是否可达 |
| `Table xxx already exists` | 忽略，应用会自动跳过已存在的表 |
