from flask import Flask, render_template, jsonify, make_response, redirect, url_for, session, request
import os
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from datetime import datetime
import sqlite3
import psutil
import csv
import io
import argparse

from werkzeug.security import generate_password_hash, check_password_hash


def resource_path(relative_path):
    """Return an absolute path for bundled and source runs."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "gpu_monitor_error.log")
DB_FILE = os.path.join(BASE_DIR, "gpu_usage.db")

app = Flask(__name__, template_folder=resource_path("templates"))
app.secret_key = os.environ.get("GPU_MONITOR_SECRET_KEY", "gpu-monitor-dev-secret")

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
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            cpu_util REAL,
            gpu_index INTEGER,
            name TEXT,
            gpu_util REAL,
            mem_util REAL,
            mem_used REAL,
            mem_total REAL,
            temp REAL,
            power REAL
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            gpu_index INTEGER,
            gpu_util REAL
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS console_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS monitor_instances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            base_url TEXT NOT NULL,
            metrics_url TEXT,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    conn.commit()

    # ensure default admin/admin
    try:
        c.execute("SELECT id FROM console_users WHERE username = ?", ("admin",))
        row = c.fetchone()
        if row is None:
            c.execute(
                "INSERT INTO console_users (username, password_hash, created_at) VALUES (?, ?, ?)",
                ("admin", generate_password_hash("admin"), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
    except Exception:
        pass

    return conn

# 全局DB连接（通过 lock 保证并发访问安全）
db_conn = init_db()

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
        cmd = ["curl", "-fsS", "--max-time", "1", metrics_url]
        txt = subprocess.check_output(cmd).decode("utf-8", errors="replace")
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
            c = db_conn.cursor()
            c.execute(
                "SELECT metrics_url FROM monitor_instances WHERE metrics_url IS NOT NULL AND metrics_url != '' ORDER BY id DESC LIMIT 1"
            )
            row = c.fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


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
            return result

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
                "used_memory_mb": max(m for _, m in gpu_list),
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

            # 添加到该进程所在的每张 GPU
            for gpu_idx, _ in gpu_list:
                result[gpu_idx].append(proc_info)

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
                # 持久化到sqlite，并记录高负载告警
                try:
                    c = db_conn.cursor()
                    for gpu in gpus:
                        c.execute(
                            "INSERT INTO samples (ts, cpu_util, gpu_index, name, gpu_util, mem_util, mem_used, mem_total, temp, power) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                            ),
                        )
                        if gpu.get('mem_util') is not None and gpu.get('mem_util') >= 90.0:
                            c.execute(
                                "INSERT INTO alerts (ts, gpu_index, gpu_util) VALUES (?, ?, ?)",
                                (timestamp, gpu.get('index'), gpu.get('mem_util')),
                            )
                    db_conn.commit()
                except Exception as e:
                    print(f"DB write error: {e}")

            time.sleep(sample_interval_seconds)
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(sample_interval_seconds)

@app.route("/")
def index():
    """主页"""
    response = make_response(render_template("index.html"))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

def _login_required(fn):
    def wrapper(*args, **kwargs):
        if not session.get("console_user"):
            return redirect(url_for("console_login"))
        return fn(*args, **kwargs)

    wrapper.__name__ = fn.__name__
    return wrapper


def _get_console_user(username):
    with lock:
        c = db_conn.cursor()
        c.execute("SELECT id, username, password_hash FROM console_users WHERE username = ?", (username,))
        return c.fetchone()


@app.route("/console/login", methods=["GET", "POST"])
def console_login():
    if request.method == "GET":
        if session.get("console_user"):
            return redirect(url_for("console_index"))
        return make_response(render_template("console_login.html", error=None))

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    row = _get_console_user(username) if username else None
    if not row:
        return make_response(render_template("console_login.html", error="账号或密码错误"))

    _, db_user, pw_hash = row
    if not check_password_hash(pw_hash, password):
        return make_response(render_template("console_login.html", error="账号或密码错误"))

    session["console_user"] = db_user
    return redirect(url_for("console_index"))


@app.route("/console/logout", methods=["POST"])
def console_logout():
    session.pop("console_user", None)
    return redirect(url_for("console_login"))


@app.route("/console")
@_login_required
def console_index():
    return make_response(render_template("console_index.html", username=session.get("console_user")))


@app.route("/console/api/instances", methods=["GET", "POST"])
@_login_required
def console_instances():
    if request.method == "GET":
        with lock:
            c = db_conn.cursor()
            c.execute(
                "SELECT id, name, base_url, metrics_url, notes FROM monitor_instances ORDER BY id DESC"
            )
            rows = c.fetchall()
        items = [
            {"id": r[0], "name": r[1], "base_url": r[2], "metrics_url": r[3], "notes": r[4]}
            for r in rows
        ]
        return jsonify({"items": items})

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    base_url = (data.get("base_url") or "").strip().rstrip("/")
    metrics_url = (data.get("metrics_url") or "").strip() or None
    notes = (data.get("notes") or "").strip() or None

    if not name or not base_url:
        return jsonify({"error": "name/base_url required"}), 400
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        return jsonify({"error": "base_url must start with http:// or https://"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with lock:
        c = db_conn.cursor()
        c.execute(
            "INSERT INTO monitor_instances (name, base_url, metrics_url, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name, base_url, metrics_url, notes, now, now),
        )
        db_conn.commit()

    return jsonify({"ok": True})


@app.route("/console/api/instances/<int:instance_id>", methods=["PUT", "DELETE"])
@_login_required
def console_instance_item(instance_id):
    if request.method == "DELETE":
        with lock:
            c = db_conn.cursor()
            c.execute("DELETE FROM monitor_instances WHERE id = ?", (instance_id,))
            db_conn.commit()
        return jsonify({"ok": True})

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    base_url = (data.get("base_url") or "").strip().rstrip("/")
    metrics_url = (data.get("metrics_url") or "").strip() or None
    notes = (data.get("notes") or "").strip() or None

    if not name or not base_url:
        return jsonify({"error": "name/base_url required"}), 400
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        return jsonify({"error": "base_url must start with http:// or https://"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with lock:
        c = db_conn.cursor()
        c.execute(
            "UPDATE monitor_instances SET name = ?, base_url = ?, metrics_url = ?, notes = ?, updated_at = ? WHERE id = ?",
            (name, base_url, metrics_url, notes, now, instance_id),
        )
        db_conn.commit()

    return jsonify({"ok": True})

@app.route("/console-root")
def console_root():
    return redirect(url_for("console_index"))


@app.route("/api/gpu-history")
def get_history():
    """获取GPU历史数据API"""
    with lock:
        return jsonify(list(gpu_data_history))


@app.route('/api/query-history')
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
        where_sql += ' AND ts >= ?'
        params.append(start)
    if end:
        where_sql += ' AND ts <= ?'
        params.append(end)
    if gpu and gpu.lower() != 'all':
        try:
            idx = int(gpu)
            where_sql += ' AND gpu_index = ?'
            params.append(idx)
        except ValueError:
            pass

    count_sql = 'SELECT COUNT(1)' + where_sql
    data_sql = 'SELECT ts, cpu_util, gpu_index, name, gpu_util, mem_util, mem_used, mem_total, temp, power FROM samples WHERE 1=1'
    data_sql += where_sql[len(' FROM samples WHERE 1=1'):] + ' ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?'
    count_params = list(params)
    data_params = list(params) + [page_size, offset]

    try:
        with lock:
            c = db_conn.cursor()
            c.execute(count_sql, count_params)
            total = c.fetchone()[0]
            c.execute(data_sql, data_params)
            rows = c.fetchall()

        def to_item(r):
            return {
                'ts': r[0], 'cpu_util': r[1], 'gpu_index': r[2], 'name': r[3], 'gpu_util': r[4], 'mem_util': r[5], 'mem_used': r[6], 'mem_total': r[7], 'temp': r[8], 'power': r[9]
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


@app.route('/api/query-history-chart')
def query_history_chart():
    """按时间范围均匀采样历史数据，用于图表趋势展示。GET 参数: start, end, gpu, sample_size"""
    start = request.args.get('start')
    end = request.args.get('end')
    gpu = request.args.get('gpu')
    sample_size = min(max(int(request.args.get('sample_size', 100)), 1), 100)

    where_sql = ' FROM samples WHERE 1=1'
    params = []
    if start:
        where_sql += ' AND ts >= ?'
        params.append(start)
    if end:
        where_sql += ' AND ts <= ?'
        params.append(end)
    if gpu and gpu.lower() != 'all':
        try:
            idx = int(gpu)
            where_sql += ' AND gpu_index = ?'
            params.append(idx)
        except ValueError:
            pass

    data_sql = 'SELECT ts, cpu_util, gpu_index, name, gpu_util, mem_util, mem_used, mem_total, temp, power FROM samples WHERE 1=1'
    data_sql += where_sql[len(' FROM samples WHERE 1=1'):] + ' ORDER BY ts ASC, id ASC'

    try:
        with lock:
            c = db_conn.cursor()
            c.execute(data_sql, params)
            rows = c.fetchall()

        def to_item(r):
            return {
                'ts': r[0], 'cpu_util': r[1], 'gpu_index': r[2], 'name': r[3], 'gpu_util': r[4], 'mem_util': r[5], 'mem_used': r[6], 'mem_total': r[7], 'temp': r[8], 'power': r[9]
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
def get_alerts():
    """返回最近的告警"""
    limit = int(request.args.get('limit', 50))
    try:
        with lock:
            c = db_conn.cursor()
            c.execute('SELECT ts, gpu_index, gpu_util FROM alerts ORDER BY id DESC LIMIT ?', (limit,))
            rows = c.fetchall()
        result = [{'ts': r[0], 'gpu_index': r[1], 'gpu_util': r[2]} for r in rows]
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/history')
def history_page():
    response = make_response(render_template('history.html'))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/api/gpu-info")
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
