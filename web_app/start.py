"""
数字孪生 Web — 一键启动器
用法: python start.py
同时启动后端 (5000) 和前端 (3000)，Ctrl+C 停止。
"""

import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend")


def is_port_in_use(port: int) -> bool:
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def kill_port(port: int):
    """杀掉占用指定端口的进程"""
    try:
        result = subprocess.run(
            ['netstat', '-ano'], capture_output=True, text=True
        )
        for line in result.stdout.split('\n'):
            if f':{port}' in line and 'LISTENING' in line:
                pid = int(line.split()[-1])
                print(f"      -> 端口 {port} 被 PID {pid} 占用，正在终止...")
                subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                              capture_output=True)
                time.sleep(0.5)
    except Exception:
        pass


def cleanup_ports():
    """清理占用的端口"""
    print("[0/3] 检查端口占用...")
    for port in [5000, 3000]:
        if is_port_in_use(port):
            kill_port(port)
    print("      完成。\n")


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

# 清理旧进程
cleanup_ports()

# 1. 后端依赖
print("[1/3] 检查后端依赖...")
subprocess.run([python, "-m", "pip", "install", "-q", "fastapi", "uvicorn", "pydantic"],
               cwd=BACKEND, stdout=subprocess.DEVNULL)

# 2. 前端依赖
print("[2/3] 检查前端依赖...")
node_modules = os.path.join(FRONTEND, "node_modules")
if not os.path.exists(node_modules):
    print("      切换到国内镜像源...")
    subprocess.run([npm_cmd, "config", "set", "registry", "https://registry.npmmirror.com"],
                   cwd=FRONTEND, capture_output=True)
    print("      正在 npm install（首次约 1-2 分钟）...")
    result = subprocess.run([npm_cmd, "install"], cwd=FRONTEND)
    if result.returncode != 0:
        print("      [!] npm install 失败，尝试继续...")
else:
    print("      已安装，跳过。")

# 3. 启动服务
print("[3/3] 启动服务...")
print()
print("  后端: http://localhost:5000")
print("  前端: http://localhost:3000")
print("  按 Ctrl+C 停止")
print()

# 使用 Popen 创建进程组，便于统一管理
backend_proc = subprocess.Popen(
    [python, "app.py"],
    cwd=BACKEND,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
    errors="replace",
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0,
)

frontend_proc = subprocess.Popen(
    [npm_cmd, "run", "dev"],
    cwd=FRONTEND,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
    errors="replace",
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0,
)

# 等几秒让服务启动
time.sleep(3)

# 检查服务是否成功启动
backend_ok = is_port_in_use(5000)
frontend_ok = is_port_in_use(3000)

if not backend_ok:
    print("[!] 后端启动失败！检查 app.py 是否有错误")
    # 读取后端输出
    if backend_proc.stdout:
        output = backend_proc.stdout.read()
        if output:
            print("后端输出:\n" + output[:500])
if not frontend_ok:
    print("[!] 前端启动失败！")
    if frontend_proc.stdout:
        output = frontend_proc.stdout.read()
        if output:
            print("前端输出:\n" + output[:500])

if backend_ok and frontend_ok:
    print("✅ 服务启动成功！")
    # 打开浏览器
    try:
        webbrowser.open("http://localhost:3000")
    except Exception:
        pass
else:
    print("\n请检查错误信息，或手动运行以下命令查看详细错误：")
    if not backend_ok:
        print(f"  cd {BACKEND} && {python} app.py")
    if not frontend_ok:
        print(f"  cd {FRONTEND} && {npm_cmd} run dev")

try:
    while True:
        if backend_proc.poll() is not None:
            print("[!] 后端已退出，代码:", backend_proc.returncode)
            break
        if frontend_proc.poll() is not None:
            print("[!] 前端已退出，代码:", frontend_proc.returncode)
            break
        time.sleep(1)
except KeyboardInterrupt:
    print("\n正在停止...")

backend_proc.terminate()
frontend_proc.terminate()
time.sleep(1)
backend_proc.kill()
frontend_proc.kill()
print("已停止。")
