"""检查训练进度"""
import time, os
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(message)s')
_error_fh = logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rl_logs', 'error.log'), encoding='utf-8')
_error_fh.setLevel(logging.ERROR)
_error_fh.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s'))
logging.getLogger().addHandler(_error_fh)

log_path = r"D:\Digital Twin\rl_logs\evaluations.npz"
while not os.path.exists(log_path):
    logger.info("等待训练生成日志...")
    time.sleep(10)

import numpy as np
data = np.load(log_path)
logger.info(f"已经评估 {len(data['results'])} 次")
logger.info(f"最佳奖励: {data['results'].max():.2f}")
logger.info(f"当前奖励: {data['results'][-1].mean():.2f}")
