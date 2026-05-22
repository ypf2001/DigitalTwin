"""快速验证 DigitalTwinGymEnv"""
import os, sys
import logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from digital_twin_gym_env import DigitalTwinGymEnv
import numpy as np

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(message)s')
_error_fh = logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rl_logs', 'error.log'), encoding='utf-8')
_error_fh.setLevel(logging.ERROR)
_error_fh.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s'))
logging.getLogger().addHandler(_error_fh)

env = DigitalTwinGymEnv(growth_stage="MID", dt_min=60.0, ep_len_days=5.0)
obs, info = env.reset()
logger.info(f"Obs shape: {obs.shape}, min={obs.min():.3f}, max={obs.max():.3f}")
logger.info(f"Obs space: {env.observation_space}")
logger.info(f"Act space: {env.action_space}")

# 跑 5 步
for i in range(5):
    action = np.array([1.0, 0.2], dtype=np.float32)
    obs, reward, terminated, truncated, info = env.step(action)
    logger.info(f"Step {i}: reward={reward:.4f}, terminated={terminated}")

logger.info("OK!")
