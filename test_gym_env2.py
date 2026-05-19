"""快速验证 DigitalTwinGymEnv"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from digital_twin_gym_env import DigitalTwinGymEnv
import numpy as np

env = DigitalTwinGymEnv(growth_stage="MID", dt_min=60.0, ep_len_days=5.0)
obs, info = env.reset()
print(f"Obs shape: {obs.shape}, min={obs.min():.3f}, max={obs.max():.3f}")
print(f"Obs space: {env.observation_space}")
print(f"Act space: {env.action_space}")

# 跑 5 步
for i in range(5):
    action = np.array([1.0, 0.2], dtype=np.float32)
    obs, reward, terminated, truncated, info = env.step(action)
    print(f"Step {i}: reward={reward:.4f}, terminated={terminated}")

print("OK!")
