"""云端 MySQL 存储 — 模型文件 + 元数据上传，自动去重"""
import os
import time
import pymysql

CLOUD_CONFIG = {
    "host": "154.44.26.212",
    "port": 61762,
    "user": "root",
    "password": "mysql_dDPsQR",
    "database": "digital_twin",
    "connect_timeout": 10,
}


def _get_conn():
    """获取连接，不指定 database（用于建库）"""
    return pymysql.connect(
        host=CLOUD_CONFIG["host"],
        port=CLOUD_CONFIG["port"],
        user=CLOUD_CONFIG["user"],
        password=CLOUD_CONFIG["password"],
        connect_timeout=CLOUD_CONFIG["connect_timeout"],
        charset="utf8mb4",
    )


def _get_db_conn():
    """获取已选择 database 的连接"""
    return pymysql.connect(
        host=CLOUD_CONFIG["host"],
        port=CLOUD_CONFIG["port"],
        user=CLOUD_CONFIG["user"],
        password=CLOUD_CONFIG["password"],
        database=CLOUD_CONFIG["database"],
        connect_timeout=CLOUD_CONFIG["connect_timeout"],
        charset="utf8mb4",
    )


def ensure_database():
    """自动建库建表（幂等）"""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{CLOUD_CONFIG['database']}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
    finally:
        conn.close()

    conn = _get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trained_models (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    name        VARCHAR(100) NOT NULL,
                    stage       VARCHAR(50),
                    steps       VARCHAR(30),
                    steps_num   INT DEFAULT 0,
                    size_mb     DECIMAL(8,2),
                    mtime       VARCHAR(20),
                    file_data   MEDIUMBLOB,
                    uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_name (name)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
        conn.commit()
    finally:
        conn.close()


def upload_model(name, stage, steps, steps_num, size_mb, mtime, file_data):
    """上传单个模型到云端（重名跳过）。
    返回 {"uploaded": True} 或 {"skipped": True, "reason": "..."}
    """
    conn = _get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM trained_models WHERE name = %s", (name,))
            if cur.fetchone():
                return {"skipped": True, "reason": f"云端已存在: {name}"}

            cur.execute(
                """INSERT INTO trained_models (name, stage, steps, steps_num, size_mb, mtime, file_data)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (name, stage, steps, steps_num, size_mb, mtime, file_data),
            )
            conn.commit()
            return {"uploaded": True}
    finally:
        conn.close()


def upload_all_models(models_dir):
    """遍历本地 rl_models/ 下所有 zip，上传到云端。返回统计结果。"""
    ensure_database()

    total = 0
    uploaded = 0
    skipped = 0
    errors = []

    if not os.path.isdir(models_dir):
        return {"total": 0, "uploaded": 0, "skipped": 0, "errors": ["模型目录不存在"]}

    for fname in sorted(os.listdir(models_dir)):
        if not fname.endswith(".zip"):
            continue

        filepath = os.path.join(models_dir, fname)
        total += 1

        try:
            # 读取文件
            with open(filepath, "rb") as f:
                file_data = f.read()

            # 元数据
            stat = os.stat(filepath)
            name = fname.replace(".zip", "")
            size_mb = round(stat.st_size / (1024 * 1024), 2)
            mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))

            # 解析 stage 和 steps（复用 get_model_info 的逻辑）
            import re
            stage_map = {"ini": "EMERGENCE", "dev": "VEGETATIVE/TUBER_INIT",
                         "mid": "BULKING", "late": "STARCH_ACCUMULATION/MATURATION"}
            stage = ""
            steps_label = ""
            steps_num = 0

            m = re.match(r"sac_(ini|dev|mid|late)_(\d+)_steps\.zip", fname)
            if m:
                stage = stage_map.get(m.group(1), m.group(1))
                steps_num = int(m.group(2))
                steps_label = f"{steps_num:,} 步"
            elif re.match(r"sac_(ini|dev|mid|late)_final\.zip", fname):
                m2 = re.match(r"sac_(ini|dev|mid|late)_final\.zip", fname)
                stage = stage_map.get(m2.group(1), m2.group(1))
                steps_num = 999999
                steps_label = "最终版"
            elif fname == "best_model.zip":
                stage = "BULKING"
                steps_label = "最佳模型"

            result = upload_model(name, stage, steps_label, steps_num, size_mb, mtime, file_data)
            if result.get("uploaded"):
                uploaded += 1
            else:
                skipped += 1
        except Exception as e:
            errors.append(f"{fname}: {e}")

    return {
        "total": total,
        "uploaded": uploaded,
        "skipped": skipped,
        "errors": errors,
    }
