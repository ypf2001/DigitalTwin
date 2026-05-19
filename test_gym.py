"""Quick test for Gymnasium wrapper."""
import sys
from gym_env import PotatoFertigationEnv
import numpy as np

env = PotatoFertigationEnv(ep_len_days=1.0)
obs, info = env.reset()
print("obs_space:", env.observation_space)
print("act_space:", env.action_space)

obs, reward, terminated, truncated, info = env.step(np.array([1.0, 0.2]))
print(f"obs shape: {obs.shape}, reward: {reward:.4f}, terminated: {terminated}")
print("Gymnasium wrapper OK")
sys.stdout.flush()
