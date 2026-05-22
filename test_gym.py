"""Quick test for Gymnasium wrapper."""
import sys
import logging
from gym_env import PotatoFertigationEnv
import numpy as np

import os

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(message)s')
_error_fh = logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rl_logs', 'error.log'), encoding='utf-8')
_error_fh.setLevel(logging.ERROR)
_error_fh.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s'))
logging.getLogger().addHandler(_error_fh)

env = PotatoFertigationEnv(ep_len_days=1.0)
obs, info = env.reset()
logger.info(f"obs_space: {env.observation_space}")
logger.info(f"act_space: {env.action_space}")

obs, reward, terminated, truncated, info = env.step(np.array([1.0, 0.2]))
logger.info(f"obs shape: {obs.shape}, reward: {reward:.4f}, terminated: {terminated}")
logger.info("Gymnasium wrapper OK")
sys.stdout.flush()
