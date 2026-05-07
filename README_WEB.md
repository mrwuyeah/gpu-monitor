# GPU 实时监控应用

一个基于 Flask + HTML 的 GPU 监控网页应用，可实时查看 GPU 计算使用率、显存占用、温度、功耗，并支持历史查询。

## 运行方式

### 方式 1：直接运行源码
```bash
pip install -r requirements.txt
python app.py
```

### 方式 2：Windows 打包
```bash
build_windows.bat
```

### 方式 3：Linux 打包
```bash
chmod +x build_linux.sh
./build_linux.sh
```

打包后可执行文件位于：
- Windows：`dist\\gpu_monitor.exe`
- Linux：`dist/gpu_monitor`

## 访问地址

- 本机：`http://localhost:5000`
- 历史页：`http://localhost:5000/history`

## 文件说明

- `app.py`：Flask 后端和数据采集
- `templates/`：前端页面
- `build_windows.bat`：Windows 打包脚本
- `build_linux.sh`：Linux 打包脚本
- `build_executable.spec`：PyInstaller 配置
- `requirements.txt`：依赖列表

## 注意事项

- 需要 NVIDIA 驱动和 `nvidia-smi`
- 历史数据默认显示最近 1 小时
- 图表对时间范围做均匀采样，最多保留 100 条用于趋势展示
