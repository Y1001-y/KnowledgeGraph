# -*- coding: utf-8 -*-
"""
数据库转换脚本：把清洗结果.xlsx 进一步转换为「技能 ↔ 岗位」多对多关系数据库
表结构：
  skill          技能表   (skill_id, skill_name, frequency 频次)
  position       岗位表   (position_id, position_name)
  skill_position 关联表   (skill_id, position_id)  —— 多对多
  position_skill_tags 岗位原始技能标签（可选，方便回溯）
输出：
  1. 技能岗位数据库.sql   —— MySQL 风格建表+插入语句
  2. 技能岗位数据库.xlsx  —— 三张表各一个 sheet + 技能频次排行
  3. 技能岗位数据库.db    —— SQLite 数据库文件，可直接用 DB Browser 打开查询
依赖：pandas openpyxl（sqlite3 为 Python 内置）
运行：python 数据库转换脚本.py
"""

import os
import sqlite3
import pandas as pd

# ============ 配置区 ============
INPUT_EXCEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "清洗结果.xlsx")
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_SQL = os.path.join(OUTPUT_DIR, "技能岗位数据库.sql")
OUTPUT_DB = os.path.join(OUTPUT_DIR, "技能岗位数据库.db")
OUTPUT_XLSX = os.path.join(OUTPUT_DIR, "技能岗位数据库.xlsx")

INVALID = {"", "nan", "none", "null", "-", "--", "无", "未注明技术", "未注明岗位"}

# ============ 1. 读取清洗结果 ============
def load_cleaned():
    if not os.path.exists(INPUT_EXCEL):
        raise FileNotFoundError(f"找不到清洗结果文件: {INPUT_EXCEL}，请先运行 数据清洗脚本.py")
    df = pd.read_excel(INPUT_EXCEL, sheet_name="岗位技术明细")
    print(f"📥 读取清洗结果: {len(df)} 行")
    return df

# ============ 2. 构建技能-岗位关系 ============
def build_tables(df):
    skill_counter = {}          # 技能 -> 出现频次（有多少个岗位需要该技能）
    skill_positions = {}        # 技能 -> 岗位名集合（去重）
    position_names = {}         # 岗位名 -> 出现次数
    raw_tag_pairs = []          # (岗位名, 原始技能标签)

    for _, row in df.iterrows():
        pos = str(row.get("position", "")).strip()
        skill_str = row.get("skill")
        if not pos or pos.lower() in INVALID:
            continue
        pos = pos if len(pos) <= 100 else pos[:100]
        position_names[pos] = position_names.get(pos, 0) + 1

        if pd.isna(skill_str):
            continue
        # 记录原始技能标签（如有）
        tags = row.get("skill_tags")
        if pd.notna(tags):
            raw_tag_pairs.append((pos, str(tags).strip()[:500]))

        for s in str(skill_str).split(", "):
            s = s.strip()
            if not s or s.lower() in INVALID:
                continue
            skill_counter[s] = skill_counter.get(s, 0) + 1
            skill_positions.setdefault(s, set()).add(pos)

    # 技能表
    skills = pd.DataFrame(
        sorted(skill_counter.items(), key=lambda kv: -kv[1]),
        columns=["skill_name", "frequency"])
    skills.insert(0, "skill_id", range(1, len(skills) + 1))
    # 关联岗位数（多对多：一个技能对应多少个不同岗位）
    skills["position_count"] = skills["skill_name"].map(
        lambda s: len(skill_positions.get(s, set())))

    # 岗位表
    positions = pd.DataFrame(
        sorted(position_names.items(), key=lambda kv: -kv[1]),
        columns=["position_name", "job_count"])
    positions.insert(0, "position_id", range(1, len(positions) + 1))

    # 关联表（去重后的多对多关系）
    pos_id = dict(zip(positions["position_name"], positions["position_id"]))
    skill_id_map = dict(zip(skills["skill_name"], skills["skill_id"]))
    rel = [(pos_id[p], skill_id_map[s])
           for s, plist in skill_positions.items() for p in plist]
    relation = pd.DataFrame(rel, columns=["position_id", "skill_id"]).drop_duplicates()

    raw_tags = pd.DataFrame(raw_tag_pairs, columns=["position_name", "skill_tags"]).drop_duplicates()

    print(f"🧮 建库完成: {len(skills)} 个技能, {len(positions)} 个岗位, "
          f"{len(relation)} 条技能-岗位关联")
    return skills, positions, relation, raw_tags

# ============ 3. 导出 SQL ============
def export_sql(skills, positions, relation, path):
    def q(v):
        return "NULL" if v is None or (isinstance(v, float) and pd.isna(v)) \
            else "'" + str(v).replace("'", "''") + "'"

    lines = [
        "-- 技能-岗位多对多关系数据库",
        "-- 表: skill(技能) / position(岗位) / skill_position(多对多关联)",
        """
DROP TABLE IF EXISTS skill_position;
DROP TABLE IF EXISTS skill;
DROP TABLE IF EXISTS position;

CREATE TABLE skill (
    skill_id       INT PRIMARY KEY,
    skill_name     VARCHAR(100) NOT NULL,
    frequency      INT DEFAULT 0,
    position_count INT DEFAULT 0
);

CREATE TABLE position (
    position_id   INT PRIMARY KEY,
    position_name VARCHAR(150) NOT NULL,
    job_count     INT DEFAULT 0
);

CREATE TABLE skill_position (
    position_id INT NOT NULL,
    skill_id    INT NOT NULL,
    PRIMARY KEY (position_id, skill_id),
    FOREIGN KEY (position_id) REFERENCES position(position_id),
    FOREIGN KEY (skill_id)    REFERENCES skill(skill_id)
);
""",
    ]
    lines += ["-- 岗位表"]
    lines += [f"INSERT INTO position (position_id, position_name, job_count) "
              f"VALUES ({r.position_id}, {q(r.position_name)}, {r.job_count});"
              for r in positions.itertuples()]
    lines += ["", "-- 技能表"]
    lines += [f"INSERT INTO skill (skill_id, skill_name, frequency, position_count) "
              f"VALUES ({r.skill_id}, {q(r.skill_name)}, {r.frequency}, {r.position_count});"
              for r in skills.itertuples()]
    lines += ["", "-- 技能-岗位关联表（多对多）"]
    lines += [f"INSERT INTO skill_position (position_id, skill_id) "
              f"VALUES ({r.position_id}, {r.skill_id});"
              for r in relation.itertuples()]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ 已导出 SQL: {path}")

# ============ 4. 导出 SQLite 数据库 ============
def export_sqlite(skills, positions, relation, path):
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    skills.to_sql("skill", conn, index=False,
                  if_exists="replace")   # 简化：直接整表写入
    positions.to_sql("position", conn, index=False, if_exists="replace")
    relation.to_sql("skill_position", conn, index=False, if_exists="replace")
    # 建索引方便查询
    conn.execute("CREATE INDEX idx_sp_skill ON skill_position(skill_id)")
    conn.execute("CREATE INDEX idx_sp_position ON skill_position(position_id)")
    conn.commit()
    conn.close()
    print(f"✅ 已导出 SQLite: {path}")

# ============ 5. 导出 Excel ============
def export_excel(skills, positions, relation, raw_tags, path):
    # 附带可读的关联明细：技能名 + 岗位名
    readable = relation.merge(positions, on="position_id").merge(
        skills[["skill_id", "skill_name", "frequency"]], on="skill_id")[
        ["skill_name", "position_name", "frequency"]]
    readable = readable.sort_values(["frequency", "skill_name"], ascending=[False, True])
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        skills.to_excel(w, sheet_name="技能表", index=False)
        positions.to_excel(w, sheet_name="岗位表", index=False)
        readable.to_excel(w, sheet_name="技能-岗位关联(可读)", index=False)
        raw_tags.to_excel(w, sheet_name="岗位原始技能标签", index=False)
    print(f"✅ 已导出 Excel: {path}")

# ============ 主流程 ============
def main():
    df = load_cleaned()
    skills, positions, relation, raw_tags = build_tables(df)
    export_sql(skills, positions, relation, OUTPUT_SQL)
    export_sqlite(skills, positions, relation, OUTPUT_DB)
    export_excel(skills, positions, relation, raw_tags, OUTPUT_XLSX)
    print("🎉 全部完成！")

if __name__ == "__main__":
    main()
