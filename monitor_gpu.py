import subprocess
import time
from datetime import datetime
import os

# 固定日志文件在当前脚本所在目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "gpu_usage_log.csv")

cmd = [
    "nvidia-smi",
    "--query-gpu=timestamp,index,name,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw",
    "--format=csv,noheader,nounits"
]

# 避免重复写表头：先判断文件是否存在
first_write = not os.path.exists(LOG_FILE)

with open(LOG_FILE, "a", encoding="utf-8") as f:
    if first_write:
        f.write("time,gpu_index,gpu_name,gpu_util_percent,mem_util_percent,mem_used_mb,mem_total_mb,temp_c,power_w\n")

    while True:
        result = subprocess.check_output(cmd).decode("utf-8").strip()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for line in result.split("\n"):
            f.write(f"{now},{line}\n")

        f.flush()
        time.sleep(1)