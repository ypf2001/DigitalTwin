"""诊断脚本：检查 PPO 模型和模拟数据"""
import os
import sys
import numpy as np

# 写入诊断日志
log_path = r"D:\Digital Twin\diagnose_log.txt"
log = open(log_path, 'w', encoding='utf-8')

def log_print(msg):
    print(msg)
    log.write(msg + '\n')

log_print("=" * 60)
log_print("诊断开始")
log_print("=" * 60)

# 1. 检查模型文件
model_path = r"D:\Digital Twin\rl_models\ppo_mid_final"
log_print(f"\n1. 检查模型: {model_path}.zip")
log_print(f"   文件存在: {os.path.exists(model_path + '.zip')}")

# 2. 尝试加载模型
try:
    from stable_baselines3 import PPO
    model = PPO.load(model_path)
    log_print(f"   模型加载成功!")
    log_print(f"   策略网络: {model.policy}")
except Exception as e:
    log_print(f"   模型加载失败: {e}")

# 3. 创建环境并运行几步
log_print(f"\n2. 创建环境并运行模拟...")
from digital_twin_gym_env import DigitalTwinGymEnv

env = DigitalTwinGymEnv(
    growth_stage="MID",
    area_ha=0.1,
    dt_min=60.0,
    ep_len_days=5.0,
    et0_mm_day=5.0,
    obs_noise_std=0.0,  # 关闭噪声以便观察
)
obs, info = env.reset()
log_print(f"   初始 obs shape: {obs.shape}")
log_print(f"   初始 obs 值: {obs}")

# 运行几步并记录
for i in range(10):
    action, _ = model.predict(obs, deterministic=True)
    obs, reward, terminated, truncated, info = env.step(action)
    log_print(f"   Step {i}: action={action}, reward={reward:.4f}, "
              f"theta={info['theta']:.4f}, ec_soil={info['ec_soil']:.4f}, "
              f"irrigation={info['irrigation_mm_h']:.4f}")
    if terminated:
        log_print(f"   模拟在第 {i} 步终止")
        break

log_print(f"\n3. 检查底层环境状态")
log_print(f"   theta={env._env.soil.theta:.4f}")
log_print(f"   ec_soil={env._env.soil.ec_soil:.4f}")
log_print(f"   time_min={env._env._time_min}")
log_print(f"   total_steps={env._env._total_steps}")

log_print(f"\n诊断完成!")
log.close()
print(f"\n诊断日志已写入: {log_path}")
