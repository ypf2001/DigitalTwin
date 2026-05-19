"""调试脚本：运行 PPO 模拟并打印输出"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 重定向输出到文件
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_output.txt")
sys.stdout = open(log_file, 'w', encoding='utf-8')
sys.stderr = sys.stdout

from main import run_simulation
run_simulation('ppo')

sys.stdout.close()
print(f"Output written to {log_file}", file=open(sys.__stdout__.fileno(), 'w'))
