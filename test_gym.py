"""Quick smoke test for the active Gymnasium wrapper."""
import logging
import os
import sys

import numpy as np

from digital_twin_gym_env import DigitalTwinGymEnv

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(message)s')
_error_fh = logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rl_logs', 'error.log'), encoding='utf-8')
_error_fh.setLevel(logging.ERROR)
_error_fh.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s'))
logging.getLogger().addHandler(_error_fh)

env = DigitalTwinGymEnv(growth_stage="MID", dt_min=5.0, ep_len_days=1.0)
obs, info = env.reset()
logger.info(f"obs_space: {env.observation_space}")
logger.info(f"act_space: {env.action_space}")
logger.info(f"obs range: min={obs.min():.3f}, max={obs.max():.3f}")

action = np.array([1.5, 6.0], dtype=np.float32)
assert env.action_space.contains(action)
obs, reward, terminated, truncated, info = env.step(action)
logger.info(f"obs shape: {obs.shape}, reward: {reward:.4f}, terminated: {terminated}")
logger.info("Gymnasium wrapper OK")
sys.stdout.flush()
