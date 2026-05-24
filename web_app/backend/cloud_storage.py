"""云端 MySQL 存储 — 模型文件 + 元数据上传，自动去重，查询"""
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
    return pymysql.connect(
        host=CLOUD_CONFIG["host"], port=CLOUD_CONFIG["port"],
        user=CLOUD_CONFIG["user"], password=CLOUD_CONFIG["password"],
        connect_timeout=CLOUD_CONFIG["connect_timeout"], charset="utf8mb4",
    )


def _get_db_conn():
    return pymysql.connect(
        host=CLOUD_CONFIG["host"], port=CLOUD_CONFIG["port"],
        user=CLOUD_CONFIG["user"], password=CLOUD_CONFIG["password"],
        database=CLOUD_CONFIG["database"],
        connect_timeout=CLOUD_CONFIG["connect_timeout"], charset="utf8mb4",
    )


def ensure_database():
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS training_progress (
                    id          INT PRIMARY KEY DEFAULT 1,
                    running     TINYINT DEFAULT 0,
                    stage       VARCHAR(50),
                    timesteps   INT DEFAULT 0,
                    target_steps INT DEFAULT 120000,
                    progress    DECIMAL(5,1) DEFAULT 0,
                    start_time  VARCHAR(30),
                    error_msg   TEXT,
                    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            # 确保有一条初始化记录
            cur.execute("INSERT IGNORE INTO training_progress (id, running) VALUES (1, 0)")
        conn.commit()
    finally:
        conn.close()


def upload_model(name, stage, steps, steps_num, size_mb, mtime, file_data):
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


def query_all_models():
    """从 MySQL 读取所有模型记录，返回与 get_model_info 相同格式"""
    ensure_database()
    conn = _get_db_conn()
    models = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, stage, steps, steps_num, size_mb, mtime, uploaded_at "
                "FROM trained_models ORDER BY uploaded_at DESC"
            )
            for row in cur.fetchall():
                models.append({
                    "name": row[0],
                    "stage": row[1],
                    "steps": row[2],
                    "steps_num": row[3] or 0,
                    "size_mb": float(row[4]) if row[4] else 0,
                    "mtime": str(row[6] or row[5])[:16],
                })
    finally:
        conn.close()
    return {"models": models, "models_dir": f"mysql://{CLOUD_CONFIG['host']}"}


def upload_all_models(models_dir, completed_only=False, progress=None):
    ensure_database()

    if not os.path.isdir(models_dir):
        if progress:
            progress["done"] = True
            progress["errors"].append("目录不存在")
        return

    import re
    stage_map = {"ini": "EMERGENCE", "dev": "VEGETATIVE/TUBER_INIT",
                 "mid": "BULKING", "late": "STARCH_ACCUMULATION/MATURATION"}

    model_list = []
    for fname in sorted(os.listdir(models_dir)):
        if not fname.endswith(".zip"):
            continue
        filepath = os.path.join(models_dir, fname)
        if not os.path.isfile(filepath):
            continue
        stat = os.stat(filepath)
        name = fname.replace(".zip", "")
        size_mb = round(stat.st_size / (1024 * 1024), 2)
        mtime_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))
        steps_num = 0
        steps_label = ""
        stage = ""

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
            continue  # 忽略

        if not stage:
            continue
        if completed_only and steps_num < 120000:
            continue

        model_list.append({
            "name": name, "stage": stage, "steps": steps_label,
            "steps_num": steps_num, "size_mb": size_mb,
            "mtime": mtime_str, "filepath": filepath,
        })

    total = len(model_list)
    uploaded = skipped = errors_count = 0
    error_list = []

    if progress:
        progress["total"] = total
        progress["uploaded"] = 0
        progress["skipped"] = 0
        progress["errors"] = []
        progress["processed"] = 0

    for m in model_list:
        if progress and progress.get("_cancel"):
            if progress:
                progress["done"] = True
                progress["errors"].append("用户取消上传")
            break

        if progress:
            progress["current"] = m["name"]

        try:
            if not os.path.isfile(m["filepath"]):
                raise FileNotFoundError("文件不存在")
            with open(m["filepath"], "rb") as f:
                file_data = f.read()
            result = upload_model(
                m["name"], m["stage"], m["steps"], m["steps_num"],
                m["size_mb"], m["mtime"], file_data,
            )
            if result.get("uploaded"):
                uploaded += 1
                if progress:
                    progress["uploaded"] = uploaded
            else:
                skipped += 1
                if progress:
                    progress["skipped"] = skipped
        except Exception as e:
            errors_count += 1
            error_list.append(f"{m['name']}: {str(e)[:80]}")
            if progress:
                progress["errors"] = error_list
                progress["skipped"] = uploaded + skipped + errors_count

        if progress:
            progress["processed"] = uploaded + skipped + errors_count

    if progress:
        progress["done"] = True


def sync_training_progress(running, stage=None, timesteps=0, target_steps=120000, progress=0, start_time=None, error_msg=None):
    """同步训练进度到云端 MySQL"""
    ensure_database()
    conn = _get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO training_progress (id, running, stage, timesteps, target_steps, progress, start_time, error_msg)
                VALUES (1, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    running=VALUES(running), stage=VALUES(stage), timesteps=VALUES(timesteps),
                    target_steps=VALUES(target_steps), progress=VALUES(progress),
                    start_time=VALUES(start_time), error_msg=VALUES(error_msg)
            """, (int(running), stage, timesteps, target_steps, round(progress, 1), start_time, error_msg))
        conn.commit()
    finally:
        conn.close()


def query_training_progress():
    """从云端读取训练进度"""
    ensure_database()
    conn = _get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT running, stage, timesteps, target_steps, progress, start_time, error_msg FROM training_progress WHERE id=1")
            row = cur.fetchone()
            if row:
                return {
                    "running": bool(row[0]), "stage": row[1],
                    "timesteps": row[2] or 0, "target_steps": row[3] or 120000,
                    "progress": float(row[4] or 0), "start_time": row[5],
                    "error": row[6],
                }
    finally:
        conn.close()
    return None
