# -*- coding: utf-8 -*-
"""pcscp 库 -> 数据快照导出（一次性 / 低频执行）。

把归档项目 MySQL 库 pcscp 的课程-技能-岗位数据导出为
data/pcscp_snapshot.json 静态快照，wiki 项目此后只读快照，
不再依赖 MySQL。

何时需要重跑本脚本：pcscp 业务库数据发生增删改之后。
    python export_pcscp.py [-H host] [-P port] [-u user] [-p password]

数据口径：
  - 课程   biz_course        deleted=0 的全部课程
  - 技能   dict_skill        level=2（level=1 作为「方向/分类」）
  - 关系   rel_course_skill  deleted=0
  - 岗位   biz_position      按 job_title 聚合；只保留「有技能要求且
                             招聘记录数排名前 25」的头部职位
  - 关系   rel_position_skill 按 (job_title, skill) 去重
"""
import argparse
import json
import os
import subprocess
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT = os.path.join(BASE_DIR, "data", "pcscp_snapshot.json")

# 头部职位数量（图谱可读性优先，可按需调大）
TOP_POSITIONS = 25
# 每个职位页面展示的招聘企业数（按记录数取前 N）
TOP_COMPANIES = 5


def _unescape(s: str) -> str:
    """mysql --batch 模式会把 \n \t \\ 转义，这里还原。"""
    return (s.replace("\\\\", "\x00").replace("\\n", "\n")
             .replace("\\t", "\t").replace("\\r", "\r").replace("\x00", "\\"))


def mysql_query(sql: str, host: str, port: str, user: str, pwd: str) -> list[list[str]]:
    """调用 mysql CLI 跑查询，返回按行拆分的 TSV 行列表。"""
    cmd = ["mysql", f"-h{host}", f"-P{port}", f"-u{user}", f"-p{pwd}",
           "--default-character-set=utf8mb4", "--batch", "-e", sql, "pcscp"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "ignore").strip())
    lines = proc.stdout.decode("utf-8").splitlines()
    rows = []
    for line in lines[1:]:  # 跳过表头
        vals = line.split("\t")
        rows.append([_unescape(v) for v in vals])
    return rows


def export(host: str, port: str, user: str, pwd: str) -> dict:
    q = lambda s: mysql_query(s, host, port, user, pwd)  # noqa: E731

    # ---- 课程 ----
    courses = [{"id": int(r[0]), "name": r[1], "code": r[2], "type": r[3] or "课程",
                "credit": float(r[4] or 0), "teacher": r[5],
                "description": r[6][:150]}
               for r in q("SELECT id, course_name, IFNULL(course_code,''),"
                          " IFNULL(course_type,''), IFNULL(credit,0),"
                          " IFNULL(teacher,''), IFNULL(description,'')"
                          " FROM biz_course WHERE deleted=0 ORDER BY id")]

    # ---- 技能（level=2；level=1 是方向） ----
    skills, directions = [], {}
    for r in q("SELECT s.id, s.skill_name, IFNULL(s.aliases,''), s.parent_id,"
               " IFNULL(p.skill_name,'方向') FROM dict_skill s"
               " LEFT JOIN dict_skill p ON s.parent_id=p.id"
               " WHERE s.deleted=0 AND s.level=2 ORDER BY s.parent_id, s.sort_order"):
        try:
            aliases = json.loads(r[2]) if r[2] else []
        except json.JSONDecodeError:
            aliases = [a for a in r[2].replace("[", "").replace("]", "")
                        .replace('"', "").split(",") if a]
        skills.append({"id": int(r[0]), "name": r[1], "aliases": aliases,
                       "level": 2, "category": r[4]})
        directions[int(r[3])] = r[4]

    # ---- 课程-技能关系 ----
    course_skill = [{"course_id": int(r[0]), "skill_id": int(r[1])}
                    for r in q("SELECT r.course_id, r.skill_id FROM rel_course_skill r"
                               " WHERE r.deleted=0")]

    # ---- 岗位：按 job_title 聚合（大小写归一，"AI工程师"/"ai工程师" 是同一职位） ----
    num = lambda v, cast=float: cast(v) if v not in ("NULL", "") else 0  # noqa: E731
    meta = {r[0]: {"recs": int(r[1]), "smin": num(r[2]),
                   "smax": num(r[3])}
            for r in q("SELECT LOWER(job_title), COUNT(*), MIN(salary_min), MAX(salary_max)"
                       " FROM biz_position WHERE deleted=0 AND job_title IN"
                       " (SELECT DISTINCT p.job_title FROM rel_position_skill r"
                       "  JOIN biz_position p ON r.position_id=p.id"
                       "  WHERE r.deleted=0 AND p.deleted=0)"
                       " GROUP BY LOWER(job_title)")}

    # 展示用标题：同一职位的多种大小写写法里取记录数最多的一种
    casing: dict[str, str] = {}
    for r in q("SELECT LOWER(job_title), job_title, COUNT(*) c FROM biz_position"
               " WHERE deleted=0 GROUP BY LOWER(job_title), job_title ORDER BY c DESC"):
        casing.setdefault(r[0], r[1])

    # 每职位的头部企业（按记录数）
    companies: dict[str, list] = {}
    for r in q("SELECT LOWER(p.job_title), IFNULL(p.company_name,'未知'), COUNT(*) c,"
               " IFNULL(MAX(p.city),'') FROM biz_position p"
               " WHERE p.deleted=0 GROUP BY LOWER(p.job_title), p.company_name"
               " ORDER BY c DESC"):
        companies.setdefault(r[0], []).append((r[1], r[3]))

    # 每职位的技能（去重）
    pos_skills: dict[str, set[int]] = {}
    for r in q("SELECT LOWER(p.job_title), r.skill_id FROM rel_position_skill r"
               " JOIN biz_position p ON r.position_id=p.id"
               " WHERE r.deleted=0 AND p.deleted=0"
               " GROUP BY LOWER(p.job_title), r.skill_id"):
        pos_skills.setdefault(r[0], set()).add(int(r[1]))

    # 只保留：技能数>=2 的头部职位（按记录数取 TOP_POSITIONS）
    picked = sorted((t for t, m in meta.items() if len(pos_skills.get(t, ())) >= 2),
                    key=lambda t: -meta[t]["recs"])[:TOP_POSITIONS]

    positions, position_skill = [], []
    pid = 0
    for key in picked:
        title = casing.get(key, key)   # 展示用原写法（如 AI工程师）
        pid += 1
        first_id = pid
        comp_list = companies.get(key, [("未知", "")])[:TOP_COMPANIES]
        for comp, city in comp_list:
            positions.append({"id": pid, "title": title, "company": comp,
                              "city": city, "recs": meta[key]["recs"],
                              "salary_min": meta[key]["smin"],
                              "salary_max": meta[key]["smax"]})
            pid += 1
        for sid in sorted(pos_skills.get(key, ())):
            position_skill.append({"position_id": first_id, "skill_id": sid})

    snap = {
        "meta": {
            "source": "MySQL pcscp（归档 vue+springboot 项目库）",
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "top_positions": TOP_POSITIONS, "top_companies": TOP_COMPANIES,
            "counts": {"courses": len(courses), "skills": len(skills),
                       "directions": len(directions),
                       "positions": len(picked),
                       "course_skill": len(course_skill),
                       "position_skill": len(position_skill)},
        },
        "directions": sorted(directions.values()),
        "courses": courses, "skills": skills, "positions": positions,
        "course_skill": course_skill, "position_skill": position_skill,
    }
    os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
    with open(SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    print(f"快照已写入 {SNAPSHOT}")
    print(json.dumps(snap["meta"]["counts"], ensure_ascii=False))
    return snap


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="导出 pcscp 库数据快照")
    ap.add_argument("-H", "--host", default="127.0.0.1")
    ap.add_argument("-P", "--port", default="3306")
    ap.add_argument("-u", "--user", default="root")
    ap.add_argument("-p", "--password", default="123456")
    a = ap.parse_args()
    export(a.host, a.port, a.user, a.password)
