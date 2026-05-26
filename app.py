from flask import Flask, render_template, jsonify, make_response, redirect, url_for, session, request
import os
import subprocess
import sys
import threading
import time
import socket
import traceback
from collections import deque
from datetime import datetime
import pymysql
import psutil
import csv
import io
import argparse
import secrets
import urllib.request
import ssl

from werkzeug.security import generate_password_hash

from auth import api_token_required, login_required, get_api_token, init_auth
from console_routes import console_bp


def resource_path(relative_path):
    """Return an absolute path for bundled and source runs."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "gpu_monitor_error.log")

# MySQL configuration — set via environment variables or defaults
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "10.70.19.243"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "model-monitor"),
    "password": os.environ.get("DB_PASSWORD", "iVDbNxcRAU1A/CcD"),
    "database": os.environ.get("DB_NAME", "gpu_monitor"),
    "charset": "utf8mb4",
}

def get_conn():
    """Create a new MySQL connection."""
    return pymysql.connect(**DB_CONFIG)

_HOST_NAME = os.environ.get("HOST_NAME", socket.gethostname())

app = Flask(__name__, template_folder=resource_path("templates"))
# session secret key will be loaded from DB in init_db()
app.secret_key = "temp-key-replaced-in-init-db"

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# 存储最近的GPU数据
gpu_data_history = deque(maxlen=360)  # 约保留最近1小时的数据（10秒采样）
current_gpu_data = {}
lock = threading.Lock()


def uniform_sample_rows(rows, sample_size):
    """对已排序数据做均匀采样，保留首尾并尽量均匀分布。"""
    if sample_size <= 0:
        return []
    if len(rows) <= sample_size:
        return rows
    if sample_size == 1:
        return [rows[-1]]

    step = (len(rows) - 1) / (sample_size - 1)
    indices = []
    for i in range(sample_size):
        idx = round(i * step)
        if idx not in indices:
            indices.append(idx)
    if indices[-1] != len(rows) - 1:
        indices[-1] = len(rows) - 1
    return [rows[i] for i in indices]

# 初始化数据库

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
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
            power DOUBLE,
            host VARCHAR(255) DEFAULT ''
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    # Add host column if upgrading from old schema
    try:
        c.execute("ALTER TABLE samples ADD COLUMN host VARCHAR(255) DEFAULT ''")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE alerts ADD COLUMN host VARCHAR(255) DEFAULT ''")
    except Exception:
        pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            ts VARCHAR(255),
            gpu_index INT,
            gpu_util DOUBLE,
            host VARCHAR(255) DEFAULT ''
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS console_users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(255) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role VARCHAR(50) NOT NULL DEFAULT 'user',
            created_at VARCHAR(255)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS monitor_instances (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            base_url TEXT NOT NULL,
            metrics_url TEXT,
            notes TEXT,
            token VARCHAR(512) DEFAULT '',
            allowed_roles VARCHAR(255) DEFAULT 'admin,senior,junior',
            created_at VARCHAR(255),
            updated_at VARCHAR(255)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS api_settings (
            `key` VARCHAR(255) PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at VARCHAR(255)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    conn.commit()

    # ensure default super admin: yofc
    try:
        c.execute("SELECT id FROM console_users WHERE username = %s", ("yofc",))
        row = c.fetchone()
        if row is None:
            c.execute(
                "INSERT INTO console_users (username, password_hash, role, created_at) VALUES (%s, %s, %s, %s)",
                ("yofc", generate_password_hash("K9#mP2$vL5@nQ8*xW3!z"), "admin", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
    except Exception:
        pass

    # ensure default API token
    try:
        c.execute("SELECT value FROM api_settings WHERE `key` = 'api_token'")
        row = c.fetchone()
        if row:
            current_token = row[0]
            print(f'当前 API 令牌: {current_token}')
        else:
            default_token = secrets.token_urlsafe(32)
            c.execute(
                "INSERT INTO api_settings (`key`, value, updated_at) VALUES (%s, %s, %s)",
                ('api_token', default_token, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
            print(f'默认 API 令牌已生成，请及时保存: {default_token}')
    except Exception:
        pass

    # ensure session secret key (persist across restarts)
    try:
        c.execute("SELECT value FROM api_settings WHERE `key` = 'session_secret'")
        row = c.fetchone()
        if row:
            app.secret_key = row[0]
        else:
            new_key = secrets.token_hex(32)
            c.execute(
                "INSERT INTO api_settings (`key`, value, updated_at) VALUES (%s, %s, %s)",
                ('session_secret', new_key, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
            app.secret_key = new_key
    except Exception:
        pass

    conn.close()
    return get_conn  # return factory function instead of connection

# 全局DB连接工厂（init_db 返回 get_conn 函数）
try:
    get_conn = init_db()
except Exception as e:
    error_text = traceback.format_exc()
    print(f"数据库连接失败: {e}")
    print(f"请检查 MySQL 是否可用，当前配置: {DB_CONFIG['host']}:{DB_CONFIG['port']}, user={DB_CONFIG['user']}")
    print(f"可通过环境变量 DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME 自定义")
    print(f"详细错误:\n{error_text}")
    with open(LOG_FILE, "a", encoding="utf-8") as log_file:
        log_file.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 数据库连接失败\n")
        log_file.write(error_text)
    sys.exit(1)

# 初始化认证模块并注册控制台蓝本
init_auth(app, get_conn, lock)
app.register_blueprint(console_bp)

def _parse_nvidia_smi_csv(text):
    text = (text or "").strip()
    if not text:
        return []
    if "No running processes found" in text:
        return []
    rows = []
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        row = [c.strip() for c in row]
        if not row or all(c == "" for c in row):
            continue
        rows.append(row)
    return rows


def get_gpu_info():
    """获取GPU信息"""
    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=index,uuid,name,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits",
        ]
        result = subprocess.check_output(cmd).decode("utf-8", errors="replace").strip()

        gpus = []
        for parts in _parse_nvidia_smi_csv(result):
            if len(parts) < 9:
                continue

            idx = int(parts[0])
            uuid = parts[1]
            name = parts[2]
            gpu_util = float(parts[3]) if parts[3] != '' else 0.0
            mem_util_raw = float(parts[4]) if parts[4] != '' else 0.0
            mem_used = float(parts[5]) if parts[5] != '' else 0.0
            mem_total = float(parts[6]) if parts[6] != '' else 0.0
            mem_util = (mem_used / mem_total * 100.0) if mem_total > 0 else mem_util_raw
            temp = float(parts[7]) if parts[7] != '' else 0.0
            power = float(parts[8]) if parts[8] != '' else 0.0

            gpu = {
                "index": idx,
                "uuid": uuid,
                "name": name,
                "gpu_util": gpu_util,
                "mem_util": mem_util,
                "mem_util_raw": mem_util_raw,
                "mem_used": mem_used,
                "mem_total": mem_total,
                "temp": temp,
                "power": power,
            }
            gpus.append(gpu)

        return gpus
    except Exception as e:
        print(f"Error getting GPU info: {e}")
        return []


def _extract_model_from_cmdline(cmdline):
    if not cmdline:
        return None
    flags = ("--model", "--served-model-name")
    for i, arg in enumerate(cmdline):
        if arg in flags and i + 1 < len(cmdline):
            return cmdline[i + 1]
    for arg in cmdline:
        if arg.startswith("--model="):
            return arg.split("=", 1)[1]
        if arg.startswith("--served-model-name="):
            return arg.split("=", 1)[1]
    # vllm serve <model_name> 位置参数
    for i, arg in enumerate(cmdline):
        if arg == "serve" and i + 1 < len(cmdline):
            candidate = cmdline[i + 1]
            if not candidate.startswith("--"):
                return candidate
    return None


def _is_vllm_process(cmdline, process_name):
    hay = " ".join(cmdline or []) + " " + (process_name or "")
    hay = hay.lower()
    if "vllm" in hay:
        return True
    return False


def _find_vllm_port(cmdline, pid):
    """从 vLLM 命令行参数中尝试提取 API 端口，用于构造 metrics URL"""
    if not cmdline:
        return "http://localhost:8000/metrics"

    for i, arg in enumerate(cmdline):
        if arg in ("--port", "--api-server-port") and i + 1 < len(cmdline):
            port = cmdline[i + 1]
            try:
                int(port)
                return f"http://localhost:{port}/metrics"
            except ValueError:
                pass
        if arg.startswith("--port="):
            port = arg.split("=", 1)[1]
            try:
                int(port)
                return f"http://localhost:{port}/metrics"
            except ValueError:
                pass
        if arg.startswith("--api-server-port="):
            port = arg.split("=", 1)[1]
            try:
                int(port)
                return f"http://localhost:{port}/metrics"
            except ValueError:
                pass

    # vLLM 默认端口 8000
    return "http://localhost:8000/metrics"


def _fetch_vllm_metrics(metrics_url):
    if not metrics_url:
        return None

    try:
        import urllib.request
        import ssl
        req = urllib.request.Request(metrics_url)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        resp = urllib.request.urlopen(req, timeout=0.5, context=ctx)
        txt = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    kv = None
    running = None
    waiting = None
    total_requests = 0
    prompt_tokens = None
    generation_tokens = None
    cache_queries = None
    cache_hits = None

    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("vllm:kv_cache_usage_perc"):
            try:
                kv = float(line.split()[-1])
            except Exception:
                pass
        elif line.startswith("vllm:num_requests_running"):
            try:
                running = float(line.split()[-1])
            except Exception:
                pass
        elif line.startswith("vllm:num_requests_waiting"):
            try:
                waiting = float(line.split()[-1])
            except Exception:
                pass
        elif line.startswith("vllm:request_success_total"):
            try:
                total_requests += float(line.split()[-1])
            except Exception:
                pass
        elif line.startswith("vllm:prompt_tokens_total ") or line.startswith("vllm:prompt_tokens_total{"):
            try:
                prompt_tokens = float(line.split()[-1])
            except Exception:
                pass
        elif line.startswith("vllm:generation_tokens_total ") or line.startswith("vllm:generation_tokens_total{"):
            try:
                generation_tokens = float(line.split()[-1])
            except Exception:
                pass
        elif line.startswith("vllm:prefix_cache_queries_total"):
            try:
                cache_queries = float(line.split()[-1])
            except Exception:
                pass
        elif line.startswith("vllm:prefix_cache_hits_total"):
            try:
                cache_hits = float(line.split()[-1])
            except Exception:
                pass

    result = {"kv_usage": kv, "running": running, "waiting": waiting, "metrics_url": metrics_url}
    if total_requests > 0:
        result["total_requests"] = total_requests
    if prompt_tokens is not None:
        result["prompt_tokens"] = prompt_tokens
    if generation_tokens is not None:
        result["generation_tokens"] = generation_tokens
    if cache_queries is not None and cache_queries > 0 and cache_hits is not None:
        result["cache_hit_rate"] = cache_hits / cache_queries

    if kv is None and running is None and waiting is None and total_requests == 0:
        return None

    return result


def _get_active_metrics_url():
    try:
        with lock:
            conn = get_conn()
            try:
                c = conn.cursor()
                c.execute(
                    "SELECT metrics_url FROM monitor_instances WHERE metrics_url IS NOT NULL AND metrics_url != '' ORDER BY id DESC LIMIT 1"
                )
                row = c.fetchone()
            finally:
                conn.close()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def _wsl_find_vllm_processes():
    """通过 wsl.exe 查询 WSL 内的 vLLM 进程，返回 [{pid, port, model_name, cmdline}, ...]"""
    try:
        output = subprocess.check_output(
            ["wsl.exe", "ps", "aux"],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode("utf-8", errors="replace")
    except Exception:
        return []

    results = []
    for line in output.splitlines():
        if "vllm" not in line.lower():
            continue
        parts = line.split(None, 10)
        if len(parts) < 11:
            continue
        try:
            pid = int(parts[1])
            cmdline_str = parts[10] if len(parts) > 10 else ""
            cmdline_parts = cmdline_str.split()
        except (ValueError, IndexError):
            continue

        # 提取端口
        port = 8000  # default
        for i, arg in enumerate(cmdline_parts):
            if arg == "--port" and i + 1 < len(cmdline_parts):
                try:
                    port = int(cmdline_parts[i + 1])
                    break
                except ValueError:
                    pass

        model_name = _extract_model_from_cmdline(cmdline_parts)
        results.append({
            "pid": pid,
            "port": port,
            "model_name": model_name,
            "cmdline": cmdline_str,
        })
    return results


def get_vllm_processes_by_gpu(gpus):
    """
    查询每张 GPU 上的 vLLM 计算进程，附带请求量和 KV 缓存指标。
    支持跨卡进程检测和多个独立 vLLM 实例（不同端口）的 metrics 采集。
    返回 {gpu_index: [{pid, name, used_memory_mb, model_name, cmdline, running, waiting, kv_usage, gpu_indices, is_cross_gpu, ...}]}
    """
    result = {g.get("index"): [] for g in gpus}

    uuid_to_idx = {}
    for g in gpus:
        uuid = g.get("uuid")
        idx = g.get("index")
        if uuid and idx is not None:
            uuid_to_idx[uuid] = idx

    try:
        cmd = [
            "nvidia-smi",
            "--query-compute-apps=pid,gpu_uuid,process_name,used_memory",
            "--format=csv,noheader",
        ]
        try:
            output = subprocess.check_output(cmd, timeout=5).decode("utf-8", errors="replace").strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            output = ""

        proc_rows = _parse_nvidia_smi_csv(output)

        # pid → [(gpu_idx, used_memory), ...]  支持跨卡：一个 PID 可能出现在多张 GPU 上
        pid_gpu_list = {}
        for parts in proc_rows:
            if len(parts) < 4:
                continue
            try:
                pid = int(parts[0])
                gpu_uuid = parts[1].strip()
                mem_str = parts[3].strip()
                used_memory = 0.0
                if mem_str not in ("[N/A]", "N/A", ""):
                    used_memory = float(mem_str)
                gpu_idx = uuid_to_idx.get(gpu_uuid)
                if gpu_idx is not None and pid > 0:
                    pid_gpu_list.setdefault(pid, []).append((gpu_idx, used_memory))
            except (ValueError, IndexError):
                continue

        if not pid_gpu_list:
            # Fallback: --query-compute-apps 返回空（新版驱动已废弃），通过 psutil 扫描 vLLM 进程
            try:
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        c = proc.info['cmdline'] or []
                        n = proc.info['name'] or ''
                        hay = ' '.join(c) + ' ' + n
                        if 'vllm' not in hay.lower():
                            continue
                        pid = proc.info['pid']
                        # 尝试通过 CUDA_VISIBLE_DEVICES 确定 GPU
                        try:
                            env = proc.environ()
                            cuda_dev = env.get('CUDA_VISIBLE_DEVICES', '')
                        except (psutil.AccessDenied, psutil.NoSuchProcess):
                            cuda_dev = ''
                        if cuda_dev:
                            for dev_id in cuda_dev.split(','):
                                try:
                                    gpu_idx = int(dev_id.strip())
                                    pid_gpu_list.setdefault(pid, []).append((gpu_idx, 0))
                                except ValueError:
                                    pass
                        else:
                            # 无法确定 GPU，关联到所有可用 GPU
                            for g in gpus:
                                pid_gpu_list.setdefault(pid, []).append((g.get("index"), 0))
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except Exception:
                pass

        if not pid_gpu_list:
            return result

        # 获取每张 GPU 的总显存使用量（用于 compute-apps 显存为 N/A 时的回退）
        gpu_total_used = {}
        try:
            mem_cmd = ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"]
            mem_out = subprocess.check_output(mem_cmd, timeout=5).decode("utf-8", errors="replace").strip()
            for line in mem_out.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) >= 2:
                    gpu_total_used[int(parts[0].strip())] = float(parts[1].strip())
        except Exception:
            pass

        # PASS 1: 扫描所有进程，找到所有 vllm serve 主进程（可能有多个独立实例）
        vllm_serve_map = {}  # pid → cmdline
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                c = proc.info['cmdline'] or []
                n = proc.info['name'] or ''
                hay = ' '.join(c) + ' ' + n
                if 'vllm' in hay.lower() and any('serve' in a for a in c):
                    vllm_serve_map[proc.info['pid']] = c
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # 递归向上查找父进程链，匹配正确的 vllm serve 实例
        def _find_vllm_serve_parent(pid, visited=None):
            if visited is None:
                visited = set()
            if pid in visited:
                return None
            visited.add(pid)
            if pid in vllm_serve_map:
                return vllm_serve_map[pid]
            try:
                parent = psutil.Process(pid).parent()
                if parent:
                    return _find_vllm_serve_parent(parent.pid, visited)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            return None

        metrics_cache = {}  # metrics_url → metrics dict 缓存，避免重复请求同一端口
        # 统计每张 GPU 上显存为 0 的 vLLM 进程数（用于回退分配）
        gpu_zero_mem_count = {}

        for pid, gpu_list in pid_gpu_list.items():
            try:
                proc = psutil.Process(pid)
                cmdline = proc.cmdline()
                proc_name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            # EngineCore 等子进程 cmdline 无意义，从父进程链找对应的 vllm serve 主进程
            if sum(1 for a in cmdline if a) <= 1:
                parent_cmdline = _find_vllm_serve_parent(pid)
                if parent_cmdline is not None:
                    cmdline = parent_cmdline
                    proc_name = 'vllm'

            if not _is_vllm_process(cmdline, proc_name):
                continue

            model_name = _extract_model_from_cmdline(cmdline)
            metrics_url = _find_vllm_port(cmdline, pid)

            proc_info = {
                "pid": pid,
                "name": proc_name,
                "model_name": model_name,
                "cmdline": " ".join(cmdline),
                "metrics_url": metrics_url,
            }

            # 从缓存读取 metrics，避免重复请求同一 URL
            if metrics_url:
                if metrics_url in metrics_cache:
                    cached = metrics_cache[metrics_url]
                    if cached:
                        proc_info.update(cached)
                else:
                    metrics = _fetch_vllm_metrics(metrics_url)
                    metrics_cache[metrics_url] = metrics
                    if metrics:
                        proc_info.update(metrics)

            # 跨卡标记
            gpu_indices = [g for g, _ in gpu_list]
            proc_info["gpu_indices"] = gpu_indices
            proc_info["is_cross_gpu"] = len(gpu_indices) > 1

            # 添加到该进程所在的每张 GPU（每张卡独立拷贝，避免共享 dict 导致的互相覆盖）
            for gpu_idx, gpu_mem in gpu_list:
                if gpu_mem == 0:
                    gpu_zero_mem_count[gpu_idx] = gpu_zero_mem_count.get(gpu_idx, 0) + 1
                gpu_proc_info = dict(proc_info)
                gpu_proc_info["used_memory_mb"] = gpu_mem
                result[gpu_idx].append(gpu_proc_info)

        # 回退：对于显存为 N/A 的进程，用 GPU 总显存用量 / 进程数 估算
        if gpu_zero_mem_count:
            for gpu_idx in gpu_zero_mem_count:
                total_used = gpu_total_used.get(gpu_idx, 0)
                zero_count = gpu_zero_mem_count[gpu_idx]
                if total_used > 0 and zero_count > 0:
                    est_per_proc = total_used / zero_count
                    for pinfo in result.get(gpu_idx, []):
                        if pinfo.get("used_memory_mb", 0) == 0:
                            pinfo["used_memory_mb"] = round(est_per_proc, 0)
        # 补充：从控制台已配置实例中采集 vLLM metrics（支持 WSL 等跨环境场景）
        try:
            with lock:
                conn = get_conn()
                try:
                    c = conn.cursor()
                    c.execute(
                        "SELECT metrics_url FROM monitor_instances WHERE metrics_url IS NOT NULL AND metrics_url != '' ORDER BY id DESC"
                    )
                    for db_row in c.fetchall():
                        murl = db_row[0]
                        if not murl:
                            continue
                        if murl in metrics_cache:
                            metrics = metrics_cache[murl]
                        else:
                            metrics = _fetch_vllm_metrics(murl)
                            metrics_cache[murl] = metrics
                        if metrics:
                            proc_info = {
                                "pid": -1,
                                "name": "vLLM (remote)",
                                "model_name": None,
                                "cmdline": "",
                                "metrics_url": murl,
                                "gpu_indices": [g.get("index") for g in gpus],
                                "is_cross_gpu": len(gpus) > 1,
                                "used_memory_mb": 0,
                            }
                            proc_info.update(metrics)
                            if proc_info.get("kv_usage") and proc_info["used_memory_mb"] == 0 and gpus:
                                proc_info["used_memory_mb"] = round(gpus[0].get("mem_total", 0) * proc_info["kv_usage"], 1)
                            for g in gpus:
                                gpu_idx = g.get("index")
                                info_copy = dict(proc_info)
                                result[gpu_idx].append(info_copy)
                finally:
                    conn.close()
        except Exception:
            pass

        # WSL 探测：通过 wsl.exe 获取 WSL 内 vLLM 进程的准确端口和 PID
        # pid_gpu_list 非空不代表识别出 vLLM（WSL 进程可见但不可读）
        has_vllm = any(len(procs) > 0 for procs in result.values())
        if not has_vllm:
            try:
                wsl_procs = _wsl_find_vllm_processes()
                for wp in wsl_procs:
                    wsl_url = f"http://localhost:{wp['port']}/metrics"
                    if wsl_url in metrics_cache:
                        continue
                    m = _fetch_vllm_metrics(wsl_url)
                    if m:
                        metrics_cache[wsl_url] = m
                        proc_info = {
                            "pid": wp["pid"],
                            "name": "vLLM (WSL)",
                            "model_name": wp["model_name"],
                            "cmdline": wp["cmdline"],
                            "metrics_url": wsl_url,
                            "gpu_indices": [g.get("index") for g in gpus],
                            "is_cross_gpu": len(gpus) > 1,
                            "used_memory_mb": 0,
                        }
                        proc_info.update(m)
                        if proc_info.get("kv_usage") and proc_info["used_memory_mb"] == 0 and gpus:
                            proc_info["used_memory_mb"] = round(gpus[0].get("mem_total", 0) * proc_info["kv_usage"], 1)
                        for g in gpus:
                            info_copy = dict(proc_info)
                            result[g.get("index")].append(info_copy)
            except Exception:
                pass

        # 回退：端口扫描（WSL 探测失败时使用）
        has_vllm2 = any(len(procs) > 0 for procs in result.values())
        if not has_vllm2:
            for port in range(8000, 8010):
                auto_url = "http://localhost:" + str(port) + "/metrics"
                if auto_url in metrics_cache:
                    continue
                try:
                    m = _fetch_vllm_metrics(auto_url)
                    if m:
                        metrics_cache[auto_url] = m
                        model_name = None
                        try:
                            import json as _json
                            model_req = urllib.request.Request("http://localhost:" + str(port) + "/v1/models")
                            model_resp = urllib.request.urlopen(model_req, timeout=1, context=ssl.create_default_context())
                            model_data = _json.loads(model_resp.read().decode("utf-8", errors="replace"))
                            if model_data.get("data"):
                                model_name = model_data["data"][0].get("id")
                        except Exception:
                            pass
                        proc_info = {
                            "pid": -1,
                            "name": "vLLM (auto)",
                            "model_name": model_name,
                            "cmdline": "auto-detected localhost:" + str(port),
                            "metrics_url": auto_url,
                            "gpu_indices": [g.get("index") for g in gpus],
                            "is_cross_gpu": len(gpus) > 1,
                            "used_memory_mb": 0,
                        }
                        proc_info.update(m)
                        if proc_info.get("kv_usage") and proc_info["used_memory_mb"] == 0 and gpus:
                            proc_info["used_memory_mb"] = round(gpus[0].get("mem_total", 0) * proc_info["kv_usage"], 1)
                        for g in gpus:
                            info_copy = dict(proc_info)
                            result[g.get("index")].append(info_copy)
                except Exception:
                    pass


    except Exception as e:
        print(f"get_vllm_processes_by_gpu error: {e}")

    return result


def monitor_gpu(sample_interval_seconds=10):
    """监控GPU及系统CPU并收集数据"""
    global current_gpu_data
    while True:
        try:
            gpus = get_gpu_info()
            vllm_by_gpu = get_vllm_processes_by_gpu(gpus)

            for g in gpus:
                g["vllm_processes"] = vllm_by_gpu.get(g.get("index"), [])

            cpu_util = psutil.cpu_percent(interval=0.1)  # CPU 使用率百分比
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            data_point = {
                "timestamp": timestamp,
                "cpu_util": cpu_util,
                "gpus": gpus,
            }

            with lock:
                current_gpu_data = data_point
                gpu_data_history.append(data_point)
                # 持久化到MySQL，并记录高负载告警
                try:
                    conn = get_conn()
                    try:
                        c = conn.cursor()
                        for gpu in gpus:
                            c.execute(
                                "INSERT INTO samples (ts, cpu_util, gpu_index, name, gpu_util, mem_util, mem_used, mem_total, temp, power, host) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                                (
                                    timestamp,
                                    cpu_util,
                                    gpu.get('index'),
                                    gpu.get('name'),
                                    gpu.get('gpu_util'),
                                    gpu.get('mem_util'),
                                    gpu.get('mem_used'),
                                    gpu.get('mem_total'),
                                    gpu.get('temp'),
                                    gpu.get('power'),
                                    _HOST_NAME,
                                ),
                            )
                            if gpu.get('mem_util') is not None and gpu.get('mem_util') >= 90.0:
                                c.execute(
                                    "INSERT INTO alerts (ts, gpu_index, gpu_util, host) VALUES (%s, %s, %s, %s)",
                                    (timestamp, gpu.get('index'), gpu.get('mem_util'), _HOST_NAME),
                                )
                        conn.commit()
                    finally:
                        conn.close()
                except Exception as e:
                    print(f"DB write error: {e}")

            time.sleep(sample_interval_seconds)
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(sample_interval_seconds)

@app.route("/")
def index():
    """主页（需通过控制台携带 ?token= 访问）"""
    response = make_response(render_template("index.html"))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response





@app.route("/console-root")
def console_root():
    return redirect(url_for("console.index"))


@app.route("/api/gpu-history")
@api_token_required
def get_history():
    """获取GPU历史数据API"""
    with lock:
        return jsonify(list(gpu_data_history))


@app.route('/api/query-history')
@api_token_required
def query_history():
    """按时间范围和GPU索引分页查询持久化样本。GET 参数: start, end, gpu, page, page_size"""
    start = request.args.get('start')  # 形如 '2026-05-07 10:00:00' 或 ISO
    end = request.args.get('end')
    gpu = request.args.get('gpu')  # 索引或 'all'
    page = max(int(request.args.get('page', 1)), 1)
    page_size = min(max(int(request.args.get('page_size', 100)), 1), 100)
    offset = (page - 1) * page_size

    where_sql = ' FROM samples WHERE 1=1'
    params = []
    if start:
        where_sql += ' AND ts >= %s'
        params.append(start)
    if end:
        where_sql += ' AND ts <= %s'
        params.append(end)
    host = request.args.get('host')
    if host:
        where_sql += ' AND host = %s'
        params.append(host)

    if gpu and gpu.lower() != 'all':
        try:
            idx = int(gpu)
            where_sql += ' AND gpu_index = %s'
            params.append(idx)
        except ValueError:
            pass

    count_sql = 'SELECT COUNT(1)' + where_sql
    data_sql = 'SELECT ts, cpu_util, gpu_index, name, gpu_util, mem_util, mem_used, mem_total, temp, power, host FROM samples WHERE 1=1'
    data_sql += where_sql[len(' FROM samples WHERE 1=1'):] + ' ORDER BY ts DESC, id DESC LIMIT %s OFFSET %s'
    count_params = list(params)
    data_params = list(params) + [page_size, offset]

    try:
        with lock:
            conn = get_conn()
            try:
                c = conn.cursor()
                c.execute(count_sql, count_params)
                total = c.fetchone()[0]
                c.execute(data_sql, data_params)
                rows = c.fetchall()
            finally:
                conn.close()

        def to_item(r):
            return {
                'ts': r[0], 'cpu_util': r[1], 'gpu_index': r[2], 'name': r[3], 'gpu_util': r[4], 'mem_util': r[5], 'mem_used': r[6], 'mem_total': r[7], 'temp': r[8], 'power': r[9], 'host': r[10]
            }

        result = [to_item(r) for r in rows]

        total_pages = max((total + page_size - 1) // page_size, 1) if total > 0 else 1

        return jsonify({
            'items': result,
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': total_pages
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/hosts')
@api_token_required
def list_hosts():
    """返回 samples 表中所有不同的主机名"""
    get_conn, lk = _get_db()
    with lk:
        conn = get_conn()
        try:
            c = conn.cursor()
            c.execute("SELECT DISTINCT host FROM samples WHERE host != '' AND host IS NOT NULL ORDER BY host ASC")
            rows = c.fetchall()
        finally:
            conn.close()
    return jsonify({"hosts": [r[0] for r in rows]})


@app.route('/api/query-history-chart')
@api_token_required
def query_history_chart():
    """按时间范围均匀采样历史数据，用于图表趋势展示。GET 参数: start, end, gpu, sample_size"""
    start = request.args.get('start')
    end = request.args.get('end')
    gpu = request.args.get('gpu')
    sample_size = min(max(int(request.args.get('sample_size', 100)), 1), 100)

    where_sql = ' FROM samples WHERE 1=1'
    params = []
    if start:
        where_sql += ' AND ts >= %s'
        params.append(start)
    if end:
        where_sql += ' AND ts <= %s'
        params.append(end)
    host = request.args.get('host')
    if host:
        where_sql += ' AND host = %s'
        params.append(host)

    if gpu and gpu.lower() != 'all':
        try:
            idx = int(gpu)
            where_sql += ' AND gpu_index = %s'
            params.append(idx)
        except ValueError:
            pass

    data_sql = 'SELECT ts, cpu_util, gpu_index, name, gpu_util, mem_util, mem_used, mem_total, temp, power, host FROM samples WHERE 1=1'
    data_sql += where_sql[len(' FROM samples WHERE 1=1'):] + ' ORDER BY ts ASC, id ASC'

    try:
        with lock:
            conn = get_conn()
            try:
                c = conn.cursor()
                c.execute(data_sql, params)
                rows = c.fetchall()
            finally:
                conn.close()

        def to_item(r):
            return {
                'ts': r[0], 'cpu_util': r[1], 'gpu_index': r[2], 'name': r[3], 'gpu_util': r[4], 'mem_util': r[5], 'mem_used': r[6], 'mem_total': r[7], 'temp': r[8], 'power': r[9], 'host': r[10]
            }

        sampled_rows = uniform_sample_rows(rows, sample_size)
        result = [to_item(r) for r in sampled_rows]
        return jsonify({
            'items': result,
            'total': len(rows),
            'sampled': len(result),
            'sample_size': sample_size
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/alerts')
@api_token_required
def get_alerts():
    """返回最近的告警"""
    limit = int(request.args.get('limit', 50))
    try:
        with lock:
            conn = get_conn()
            try:
                c = conn.cursor()
                c.execute('SELECT ts, gpu_index, gpu_util FROM alerts ORDER BY id DESC LIMIT %s', (limit,))
                rows = c.fetchall()
            finally:
                conn.close()
        result = [{'ts': r[0], 'gpu_index': r[1], 'gpu_util': r[2]} for r in rows]
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/history')
def history_page():
    """历史页（需通过控制台携带 ?token= 访问）"""
    response = make_response(render_template('history.html'))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/api/gpu-info")
@api_token_required
def get_gpu():
    """获取当前GPU信息API"""
    with lock:
        return jsonify(current_gpu_data)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GPU 实时监控系统")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    parser.add_argument("--port", type=int, default=5000, help="监听端口（默认 5000）")
    args = parser.parse_args()

    try:
        print("GPU监控服务启动中...")
        print(f"请在浏览器打开: http://localhost:{args.port}")
        print(f"控制台: http://localhost:{args.port}/console")
        print(f"日志文件: {LOG_FILE}")

        monitor_thread = threading.Thread(target=monitor_gpu, daemon=True)
        monitor_thread.start()

        app.run(debug=False, host=args.host, port=args.port)
    except Exception:
        error_text = traceback.format_exc()
        print(error_text)
        with open(LOG_FILE, "a", encoding="utf-8") as log_file:
            log_file.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n")
            log_file.write(error_text)
        raise
