"""
数字孪生 Web — 一键启动器
用法: python start.py
同时启动后端 (5000) 和前端 (3000)，Ctrl+C 停止。
"""

import os
import subprocess
import sys
import time
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend")

# ---- 找 Python ----
python = None
for p in [
    r"C:\Users\Administrator\.conda\envs\digital-twin\python.exe",
    r"C:\Users\Administrator\miniconda3\envs\digital-twin\python.exe",
    r"C:\Users\Administrator\anaconda3\envs\digital-twin\python.exe",
]:
    if os.path.exists(p):
        python = p
        break
if python is None:
    python = sys.executable

# ---- 找 npm ----
npm_cmd = None
for p in [
    r"D:\nodejs\npm.cmd",
    r"C:\Program Files\nodejs\npm.cmd",
    r"C:\Program Files (x86)\nodejs\npm.cmd",
]:
    if os.path.exists(p):
        npm_cmd = p
        break
if npm_cmd is None:
    npm_cmd = "npm.cmd"

print("=" * 50)
print("  马铃薯施肥灌溉数字孪生系统 — Web")
print("=" * 50)
print()

# 1. 后端依赖
print("[1/3] 检查后端依赖...")
subprocess.run([python, "-m", "pip", "install", "-q", "fastapi", "uvicorn", "pydantic"],
               cwd=BACKEND)

# 2. 前端依赖
print("[2/3] 检查前端依赖...")
node_modules = os.path.join(FRONTEND, "node_modules")
if not os.path.exists(node_modules):
    print("      切换到国内镜像源...")
    subprocess.run([npm_cmd, "config", "set", "registry", "https://registry.npmmirror.com"],
                   cwd=FRONTEND, capture_output=True)
    print("      正在 npm install（首次约 1-2 分钟）...")
    subprocess.run([npm_cmd, "install"], cwd=FRONTEND)
else:
    print("      已安装，跳过。")

# 3. 启动服务
print("[3/3] 启动服务...")
print()
print("  后端: http://localhost:5000")
print("  前端: http://localhost:3000")
print("  按 Ctrl+C 停止")
print()

backend_proc = subprocess.Popen(
    [python, "app.py"], cwd=BACKEND,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, encoding="utf-8", errors="replace",
)

frontend_proc = subprocess.Popen(
    [npm_cmd, "run", "dev"], cwd=FRONTEND,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, encoding="utf-8", errors="replace",
)

# 等前端启动后打开浏览器
time.sleep(4)
try:
    webbrowser.open("http://localhost:3000")
except Exception:
    pass

try:
    while True:
        if backend_proc.poll() is not None:
            print("[!] 后端已退出")
            break
        if frontend_proc.poll() is not None:
            print("[!] 前端已退出")
            break
        time.sleep(1)
except KeyboardInterrupt:
    print("\n正在停止...")

backend_proc.terminate()
frontend_proc.terminate()
print("已停止。")
