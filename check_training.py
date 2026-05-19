"""检查训练进度"""
import time, os

log_path = r"D:\Digital Twin\rl_logs\evaluations.npz"
while not os.path.exists(log_path):
    print("等待训练生成日志...")
    time.sleep(10)

import numpy as np
data = np.load(log_path)
print(f"已经评估 {len(data['results'])} 次")
print(f"最佳奖励: {data['results'].max():.2f}")
print(f"当前奖励: {data['results'][-1].mean():.2f}")
