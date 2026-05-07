from flask import Flask, render_template, jsonify, make_response
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


def resource_path(relative_path):
    """Return an absolute path for bundled and source runs."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "gpu_monitor_error.log")
DB_FILE = os.path.join(BASE_DIR, "gpu_usage.db")

app = Flask(__name__, template_folder=resource_path("templates"))

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
    conn.commit()
    return conn

# 全局DB连接（通过 lock 保证并发访问安全）
db_conn = init_db()

def get_gpu_info():
    """获取GPU信息"""
    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=index,name,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits"
        ]
        result = subprocess.check_output(cmd).decode("utf-8").strip()
        
        gpus = []
        for line in result.split("\n"):
            if line.strip():
                parts = line.split(", ")
                # 基于 memory.used / memory.total 重新计算显存使用率，避免 driver 返回异常值
                idx = int(parts[0])
                name = parts[1]
                gpu_util = float(parts[2]) if parts[2] != '' else 0.0
                mem_util_raw = float(parts[3]) if parts[3] != '' else 0.0
                mem_used = float(parts[4]) if parts[4] != '' else 0.0
                mem_total = float(parts[5]) if parts[5] != '' else 0.0
                # 防止除0
                mem_util = (mem_used / mem_total * 100.0) if mem_total > 0 else mem_util_raw
                temp = float(parts[6]) if parts[6] != '' else 0.0
                power = float(parts[7]) if parts[7] != '' else 0.0

                gpu = {
                    "index": idx,
                    "name": name,
                    "gpu_util": gpu_util,
                    "mem_util": mem_util,
                    "mem_util_raw": mem_util_raw,
                    "mem_used": mem_used,
                    "mem_total": mem_total,
                    "temp": temp,
                    "power": power
                }
                gpus.append(gpu)
        return gpus
    except Exception as e:
        print(f"Error getting GPU info: {e}")
        return []

def monitor_gpu():
    """监控GPU及系统CPU并收集数据"""
    global current_gpu_data
    while True:
        try:
            gpus = get_gpu_info()
            cpu_util = psutil.cpu_percent(interval=0.1)  # CPU 使用率百分比
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            data_point = {
                "timestamp": timestamp,
                "cpu_util": cpu_util,
                "gpus": gpus
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
                            (timestamp, cpu_util, gpu.get('index'), gpu.get('name'), gpu.get('gpu_util'), gpu.get('mem_util'), gpu.get('mem_used'), gpu.get('mem_total'), gpu.get('temp'), gpu.get('power'))
                        )
                        if gpu.get('mem_util') is not None and gpu.get('mem_util') >= 90.0:
                            c.execute(
                                "INSERT INTO alerts (ts, gpu_index, gpu_util) VALUES (?, ?, ?)",
                                (timestamp, gpu.get('index'), gpu.get('mem_util'))
                            )
                    db_conn.commit()
                except Exception as e:
                    print(f"DB write error: {e}")

            time.sleep(10)
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(10)

@app.route("/")
def index():
    """主页"""
    response = make_response(render_template("index.html"))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route("/api/gpu-info")
def get_gpu():
    """获取当前GPU信息API"""
    with lock:
        return jsonify(current_gpu_data)

@app.route("/api/gpu-history")
def get_history():
    """获取GPU历史数据API"""
    with lock:
        return jsonify(list(gpu_data_history))


@app.route('/api/query-history')
def query_history():
    """按时间范围和GPU索引分页查询持久化样本。GET 参数: start, end, gpu, page, page_size"""
    from flask import request
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
    from flask import request
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
    from flask import request
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

if __name__ == "__main__":
    try:
        # 启动GPU监控线程
        monitor_thread = threading.Thread(target=monitor_gpu, daemon=True)
        monitor_thread.start()

        # 启动Flask服务器
        print("GPU监控服务启动中...")
        print("请在浏览器打开: http://localhost:5000")
        print(f"日志文件: {LOG_FILE}")
        app.run(debug=False, host="0.0.0.0", port=5000)
    except Exception:
        error_text = traceback.format_exc()
        print(error_text)
        with open(LOG_FILE, "a", encoding="utf-8") as log_file:
            log_file.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n")
            log_file.write(error_text)
        raise
