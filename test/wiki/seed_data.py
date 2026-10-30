# -*- coding: utf-8 -*-
"""源数据层：从 data/pcscp_snapshot.json 数据快照加载业务数据到本地 SQLite。

快照由 export_pcscp.py 一次性从归档项目 MySQL 库 pcscp 导出，
日常运行（seed/ingest/build_graph）不依赖 MySQL；
只有 pcscp 业务库数据变更后才需要重跑 export_pcscp.py。

数据模型（与归档项目对齐）：
  course / skill / position / course_skill / position_skill
"""
import json
import os
import sqlite3

from config import BASE_DIR, SOURCE_DB

SNAPSHOT = os.path.join(BASE_DIR, "data", "pcscp_snapshot.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS course (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    code    TEXT,
    type    TEXT,
    credit  REAL,
    teacher TEXT,
    description TEXT
);
CREATE TABLE IF NOT EXISTS skill (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    level     INTEGER,
    category  TEXT,
    aliases   TEXT
);
CREATE TABLE IF NOT EXISTS position (
    id       INTEGER PRIMARY KEY,
    title    TEXT NOT NULL,
    company  TEXT,
    city     TEXT,
    recs     INTEGER,
    salary_min REAL,
    salary_max REAL
);
CREATE TABLE IF NOT EXISTS course_skill (
    course_id INTEGER NOT NULL,
    skill_id  INTEGER NOT NULL,
    PRIMARY KEY (course_id, skill_id)
);
CREATE TABLE IF NOT EXISTS position_skill (
    position_id INTEGER NOT NULL,
    skill_id    INTEGER NOT NULL,
    PRIMARY KEY (position_id, skill_id)
);
"""


def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(SOURCE_DB), exist_ok=True)
    conn = sqlite3.connect(SOURCE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def load_snapshot() -> dict:
    """读取数据快照（不依赖 MySQL）。"""
    if not os.path.exists(SNAPSHOT):
        raise FileNotFoundError(
            f"数据快照不存在: {SNAPSHOT}\n"
            f"请先运行一次: python export_pcscp.py（需 MySQL 可用）")
    with open(SNAPSHOT, encoding="utf-8") as f:
        return json.load(f)


def seed() -> dict:
    """快照 -> 本地 SQLite（可重复执行，全量重建）。"""
    snap = load_snapshot()
    with get_conn() as conn:
        # 全量重建（表结构随版本演进，直接 DROP 再建）
        conn.executescript("""
DROP TABLE IF EXISTS course_skill; DROP TABLE IF EXISTS position_skill;
DROP TABLE IF EXISTS course; DROP TABLE IF EXISTS skill; DROP TABLE IF EXISTS position;
""" + SCHEMA)
        conn.executemany(
            "INSERT INTO course VALUES (?,?,?,?,?,?,?)",
            [(c["id"], c["name"], c.get("code", ""), c.get("type", "课程"),
              c.get("credit", 0), c.get("teacher", ""), c.get("description", ""))
             for c in snap["courses"]])
        conn.executemany(
            "INSERT INTO skill VALUES (?,?,?,?,?)",
            [(s["id"], s["name"], s["level"], s["category"],
              json.dumps(s.get("aliases", []), ensure_ascii=False))
             for s in snap["skills"]])
        conn.executemany(
            "INSERT INTO position VALUES (?,?,?,?,?,?,?)",
            [(p["id"], p["title"], p.get("company", ""), p.get("city", ""),
              p.get("recs", 0), p.get("salary_min", 0), p.get("salary_max", 0))
             for p in snap["positions"]])
        conn.executemany(
            "INSERT INTO course_skill VALUES (?,?)",
            [(r["course_id"], r["skill_id"]) for r in snap["course_skill"]])
        conn.executemany(
            "INSERT INTO position_skill VALUES (?,?)",
            [(r["position_id"], r["skill_id"]) for r in snap["position_skill"]])
    cnt = snap["meta"]["counts"]
    print(f"快照已载入 {SOURCE_DB}（{cnt['courses']}课程/{cnt['skills']}技能/"
          f"{cnt['positions']}职位标题/{cnt['course_skill']}+{cnt['position_skill']}关系）")
    return snap


def fetch_all() -> dict:
    """摄取/构图统一的数据入口。"""
    with get_conn() as conn:
        return {
            "courses": [dict(r) for r in conn.execute("SELECT * FROM course ORDER BY id")],
            "skills": [dict(r) for r in conn.execute("SELECT * FROM skill ORDER BY id")],
            "positions": [dict(r) for r in conn.execute("SELECT * FROM position ORDER BY id")],
            "course_skill": [dict(r) for r in conn.execute("SELECT * FROM course_skill")],
            "position_skill": [dict(r) for r in conn.execute("SELECT * FROM position_skill")],
        }


if __name__ == "__main__":
    seed()
