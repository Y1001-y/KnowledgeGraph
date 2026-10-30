# -*- coding: utf-8 -*-
"""源数据库：仿照归档项目（课程-岗位-技能匹配平台）的数据模型，
把课程/技能/岗位及关系存入 SQLite，作为知识图谱的数据源头。"""
import os
import sqlite3

from config import SOURCE_DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS course (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    code    TEXT,
    type    TEXT,
    credit  REAL
);
CREATE TABLE IF NOT EXISTS skill (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    level     INTEGER,
    category  TEXT
);
CREATE TABLE IF NOT EXISTS position (
    id       INTEGER PRIMARY KEY,
    title    TEXT NOT NULL,
    company  TEXT,
    city     TEXT
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

# ---------------- 课程（22 门） ----------------
COURSES = [
    (1,  "Java程序设计",     "CS101", "专业课",     4.0),
    (2,  "数据结构",         "CS102", "专业基础课", 3.5),
    (3,  "数据库原理",       "CS103", "专业基础课", 3.0),
    (4,  "Python数据分析",   "CS204", "选修课",     2.5),
    (5,  "机器学习",         "CS305", "专业课",     3.0),
    (6,  "Web前端开发",      "CS206", "选修课",     2.5),
    (7,  "软件工程",         "CS301", "专业课",     3.0),
    (8,  "计算机网络",       "CS202", "专业基础课", 3.0),
    (9,  "操作系统",         "CS203", "专业基础课", 3.5),
    (10, "算法设计与分析",   "CS304", "专业课",     3.0),
    (11, "移动应用开发",     "CS307", "选修课",     2.5),
    (12, "大数据技术",       "CS306", "专业课",     3.0),
    (13, "云计算与分布式",   "CS401", "专业课",     3.0),
    (14, "信息安全",         "CS308", "选修课",     2.5),
    (15, "深度学习",         "CS402", "专业课",     3.0),
    (16, "软件测试",         "CS302", "专业课",     2.5),
    (17, "编译原理",         "CS303", "专业基础课", 3.0),
    (18, "Linux系统编程",    "CS205", "选修课",     2.0),
    (19, "软件体系结构",     "CS403", "专业课",     2.5),
    (20, "自然语言处理",     "CS404", "选修课",     2.5),
    (21, "计算机视觉",       "CS405", "选修课",     2.5),
    (22, "DevOps实践",       "CS406", "选修课",     2.0),
]

# ---------------- 技能（42 项，10 个方向） ----------------
SKILLS = [
    # 后端开发
    (1,  "Java",           2, "后端开发"), (2,  "Spring Boot",   3, "后端开发"),
    (3,  "Spring Cloud",   3, "后端开发"), (4,  "MyBatis",       3, "后端开发"),
    (5,  "微服务架构",     3, "后端开发"), (6,  "消息队列",      3, "后端开发"),
    # 前端开发
    (7,  "HTML/CSS",       3, "前端开发"), (8,  "JavaScript",    3, "前端开发"),
    (9,  "Vue",            3, "前端开发"), (10, "React",         3, "前端开发"),
    (11, "TypeScript",     3, "前端开发"), (12, "小程序开发",    3, "前端开发"),
    # 数据库
    (13, "MySQL",          3, "数据库"),   (14, "SQL",           3, "数据库"),
    (15, "Redis",          3, "数据库"),   (16, "MongoDB",       3, "数据库"),
    (17, "SQL调优",        3, "数据库"),
    # 计算机基础
    (18, "数据结构与算法", 2, "计算机基础"), (19, "网络协议",     3, "计算机基础"),
    (20, "操作系统原理",   3, "计算机基础"), (21, "编译原理基础", 3, "计算机基础"),
    # 人工智能
    (22, "Python",         2, "人工智能"), (23, "机器学习",      2, "人工智能"),
    (24, "深度学习",       3, "人工智能"), (25, "自然语言处理",  3, "人工智能"),
    (26, "计算机视觉",     3, "人工智能"), (27, "PyTorch",       3, "人工智能"),
    # 大数据
    (28, "Hadoop",         3, "大数据"),   (29, "Spark",         3, "大数据"),
    (30, "Flink",          3, "大数据"),   (31, "数据仓库",      3, "大数据"),
    # 软件工程
    (32, "软件测试",       3, "软件工程"), (33, "需求分析",      3, "软件工程"),
    (34, "Git",            3, "软件工程"), (35, "软件设计模式",  3, "软件工程"),
    # 运维/云
    (36, "Linux",          3, "云计算运维"), (37, "Docker",      3, "云计算运维"),
    (38, "Kubernetes",     3, "云计算运维"), (39, "CI/CD",       3, "云计算运维"),
    # 移动开发
    (40, "Android",        3, "移动开发"), (41, "uni-app",       3, "移动开发"),
    # 信息安全
    (42, "Web安全",        3, "信息安全"),
]

# ---------------- 岗位（14 类，多公司） ----------------
POSITIONS = [
    (1,  "Java开发工程师",   "华为",       "深圳"),
    (2,  "Java开发工程师",   "中兴",       "南京"),
    (3,  "Java开发工程师",   "工商银行",   "北京"),
    (4,  "前端开发工程师",   "腾讯",       "深圳"),
    (5,  "前端开发工程师",   "字节跳动",   "北京"),
    (6,  "数据分析师",       "美团",       "北京"),
    (7,  "算法工程师",       "字节跳动",   "北京"),
    (8,  "算法工程师",       "商汤科技",   "上海"),
    (9,  "大数据开发工程师", "阿里云",     "杭州"),
    (10, "数据库管理员",     "阿里云",     "杭州"),
    (11, "测试工程师",       "小米",       "武汉"),
    (12, "运维工程师",       "腾讯",       "深圳"),
    (13, "安全工程师",       "奇安信",     "北京"),
    (14, "Android开发工程师", "OPPO",      "深圳"),
]

# 课程 -> 技能
COURSE_SKILL = [
    (1, 1), (1, 2), (1, 4), (1, 15),
    (2, 18),
    (3, 13), (3, 14),
    (4, 22), (4, 14), (4, 31),
    (5, 22), (5, 23), (5, 27),
    (6, 7), (6, 8), (6, 9), (6, 12),
    (7, 33), (7, 35), (7, 18),
    (8, 19),
    (9, 20), (9, 36),
    (10, 18),
    (11, 40), (11, 41), (11, 8),
    (12, 28), (12, 29), (12, 31),
    (13, 5), (13, 37), (13, 3),
    (14, 42), (14, 19),
    (15, 24), (15, 27), (15, 22),
    (16, 32), (16, 34),
    (17, 21),
    (18, 36), (18, 20),
    (19, 2), (19, 5), (19, 35),
    (20, 25), (20, 24), (20, 22),
    (21, 26), (21, 27), (21, 24),
    (22, 39), (22, 37), (22, 38), (22, 34),
]

# 岗位 -> 技能
POSITION_SKILL = [
    (1, 1), (1, 2), (1, 4), (1, 13), (1, 15), (1, 6),
    (2, 1), (2, 2), (2, 36), (2, 34),
    (3, 1), (3, 2), (3, 13), (3, 14),
    (4, 7), (4, 8), (4, 9), (4, 11),
    (5, 8), (5, 10), (5, 11), (5, 9),
    (6, 22), (6, 14), (6, 13), (6, 31),
    (7, 22), (7, 23), (7, 24), (7, 27), (7, 25),
    (8, 23), (8, 24), (8, 26), (8, 27),
    (9, 28), (9, 29), (9, 30), (9, 31), (9, 36),
    (10, 13), (10, 14), (10, 15), (10, 17), (10, 16),
    (11, 32), (11, 22), (11, 34),
    (12, 36), (12, 37), (12, 38), (12, 39), (12, 19),
    (13, 42), (13, 19), (13, 36),
    (14, 40), (14, 8), (14, 34),
]


def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(SOURCE_DB), exist_ok=True)
    conn = sqlite3.connect(SOURCE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def seed() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.execute("DELETE FROM course_skill")
        conn.execute("DELETE FROM position_skill")
        conn.execute("DELETE FROM course")
        conn.execute("DELETE FROM skill")
        conn.execute("DELETE FROM position")
        conn.executemany("INSERT INTO course VALUES (?,?,?,?,?)", COURSES)
        conn.executemany("INSERT INTO skill VALUES (?,?,?,?)", SKILLS)
        conn.executemany("INSERT INTO position VALUES (?,?,?,?)", POSITIONS)
        conn.executemany("INSERT INTO course_skill VALUES (?,?)", COURSE_SKILL)
        conn.executemany("INSERT INTO position_skill VALUES (?,?)", POSITION_SKILL)
    print(f"种子数据已写入 {SOURCE_DB}（{len(COURSES)}课程/{len(SKILLS)}技能/{len(POSITIONS)}岗位）")


def fetch_all() -> dict:
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
