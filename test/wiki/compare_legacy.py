# -*- coding: utf-8 -*-
"""旧项目(MySQL pcscp 基准) vs 新测试项目(MediaWiki 图谱) 全量比对。

比对层级：
  L1 课程节点   L2 技能节点(含别名)   L3 岗位节点(标题合并口径)
  L4 课程-技能边  L5 岗位-技能边(按职位Top技能覆盖率)
输出：控制台报告 + 比对报告.md + 人工核对清单.csv
"""
import csv
import json
import os
from collections import Counter, defaultdict

import config

LEGACY = os.path.join(config.BASE_DIR, "data", "legacy")
REPORT = os.path.join(config.BASE_DIR, "比对报告.md")
CSV_OUT = os.path.join(config.BASE_DIR, "人工核对清单.csv")


def tsv(name):
    with open(os.path.join(LEGACY, name), encoding="utf-8") as f:
        rows = [l.rstrip("\n").split("\t") for l in f if l.strip()]
    return rows[0], rows[1:]


def norm(s: str) -> str:
    s = (s or "").strip().lower().replace(" ", "")
    if s.endswith("（课程）"):
        s = s[:-4]
    if s.endswith("（技能）"):
        s = s[:-4]
    return s


def split_aliases(raw: str) -> list[str]:
    for ch in "[]\"'":
        raw = raw.replace(ch, " ")
    return [a.strip() for a in raw.replace("，", ",").replace("；", ";").replace(";", ",").replace("|", ",").split(",") if a.strip()]


def main():
    _, courses = tsv("courses.tsv")            # id, course_name, course_type
    _, skills = tsv("skills.tsv")              # id, skill_name, aliases, parent_id, level
    _, cs = tsv("course_skill.tsv")            # course_name, skill_name
    _, ps = tsv("position_skill.tsv")          # job_title, skill_name, count

    with open(config.GRAPH_DATA, encoding="utf-8") as f:
        g = json.load(f)
    nodes = g["nodes"]
    by_type = defaultdict(list)
    for n in nodes:
        by_type[n["type"]].append(n["name"])
    edges = {(norm(l["source"]), norm(l["target"])) for l in g["links"]}
    es = set()
    for a, b in edges:
        es.add(frozenset((a, b)))

    # 技能别名表：alias_norm -> 标准名
    alias = {}
    for r in skills:
        for a in split_aliases(r[2]):
            alias.setdefault(norm(a), r[1])

    def has_edge(a, b):
        return frozenset((norm(a), norm(b))) in es

    checklist = []  # [对象, 层, 期望(基准), 实际(新图), 结论, 备注]
    rep = ["# 新旧项目知识图谱比对报告", "",
           f"- 基准：旧项目 MySQL（pcscp 库，Neo4j 同步源）",
           f"- 被测：test/wiki MediaWiki 图谱（graph_data.json，{len(nodes)} 节点 / {len(g['links'])} 边）",
           "- 口径说明：旧图谱每条招聘记录一个岗位节点（21400 条）；新图谱按职位合并（10 页），"
           "因此岗位层按「职位标题」对齐，边按「该职位的 Top 频技能」对齐。", ""]

    # ---------- L1 课程 ----------
    legacy_courses = {r[1] for r in courses}
    new_courses = set(by_type["课程"])
    matched_c = {c for c in legacy_courses if norm(c) in {norm(x) for x in new_courses}}
    miss_c = sorted(legacy_courses - matched_c)
    extra_c = sorted(x for x in new_courses if norm(x) not in {norm(c) for c in legacy_courses})
    rep += [f"## L1 课程节点：旧 {len(legacy_courses)} vs 新 {len(new_courses)}",
            f"- 名称可对上：**{len(matched_c)}/{len(legacy_courses)}**",
            f"- 旧有新无（缺失 {len(miss_c)}）：{'、'.join(miss_c) or '无'}",
            f"- 新有旧无（额外 {len(extra_c)}，来自手写种子数据）：{'、'.join(extra_c) or '无'}", ""]
    for c in sorted(legacy_courses):
        checklist.append([c, "L1课程", "旧库存在", "图谱中" if norm(c) in {norm(x) for x in new_courses} else "图谱中缺失", "", ""])
    for c in extra_c:
        checklist.append([c, "L1课程", "旧库查无(额外)", "图谱中存在", "", ""])

    # ---------- L2 技能 ----------
    # 旧库 dict_skill 分两层：level=2 是具体技能（对齐新图「技能」节点），
    # level=1 是技能方向（新模型里做成「概念-方向」聚合页，单独对齐）
    legacy_skills = {r[1] for r in skills if r[4] == "2"}
    legacy_dirs = {r[1] for r in skills if r[4] == "1"}
    new_skills = set(by_type["技能"])
    new_concepts = {n[3:] for n in by_type["概念"] if n.startswith("概念-")}
    ns_norm = {norm(x): x for x in new_skills}
    matched_s, miss_s = set(), {}
    for s in legacy_skills:
        n = norm(s)
        hit = n in ns_norm or n in alias and norm(alias[n]) in ns_norm
        (matched_s if hit else miss_s).add(s) if hit else miss_s.setdefault(s, True)
    extra_s = sorted(x for x in new_skills
                     if norm(x) not in {norm(s) for s in legacy_skills}
                     and norm(x) not in {norm(a) for a in alias})
    dir_ok = {d for d in legacy_dirs if norm(d) in {norm(x) for x in new_concepts}}
    dir_miss = sorted(legacy_dirs - dir_ok)
    rep += [f"## L2 技能节点：旧 level-2 技能 {len(legacy_skills)} vs 新技能节点 {len(new_skills)}",
            f"- 名称/别名可对上：**{len(matched_s)}/{len(legacy_skills)}**",
            f"- 旧有新无（缺失 {len(miss_s)}）：",
            "".join(f"  - {s}\n" for s in sorted(miss_s)) or "  - 无",
            f"- 新有旧无（额外 {len(extra_s)}）：{'、'.join(extra_s) or '无'}", "",
            f"## L2b 技能方向：旧 level-1 方向 {len(legacy_dirs)} vs 新概念页 {len(new_concepts)}",
            f"- 方向可对上：**{len(dir_ok)}/{len(legacy_dirs)}**"
            + (f"（缺失：{'、'.join(dir_miss)}）" if dir_miss else ""), ""]
    for s in sorted(miss_s):
        checklist.append([s, "L2技能", "旧技能字典存在", "图谱中缺失", "", ""])
    for s in extra_s:
        checklist.append([s, "L2技能", "旧库查无(额外)", "图谱中存在", "", ""])
    for d in sorted(dir_miss):
        checklist.append([d, "L2b方向", "旧技能方向存在", "概念页缺失", "", ""])

    # ---------- L3 岗位 ----------
    legacy_titles = {r[0] for r in ps}
    new_pos = set(by_type["岗位"])
    exact, fuzzy, miss_p = [], [], []
    for p in sorted(new_pos):
        if norm(p) in {norm(t) for t in legacy_titles}:
            exact.append(p)
        else:
            miss_p.append(p)
    title_count = Counter(r[0] for r in ps)
    rep += [f"## L3 岗位节点：旧 {len(legacy_titles)} 种职位标题（12338 种去重标题中，有技能关联的 {len(legacy_titles)} 种） vs 新 {len(new_pos)} 页",
            f"- 新页面标题在旧库中能精确找到：**{len(exact)}/{len(new_pos)}**",
            f"- 新页面标题旧库查无：{'、'.join(miss_p) or '无'}", ""]
    for p in sorted(new_pos):
        cnt = title_count.get(p, 0)
        checklist.append([p, "L3岗位", f"旧库该职位 {cnt} 条记录", "图谱中存在" if p in exact else "标题未精确匹配", "", ""])
    for p in miss_p:
        rep += [f"  - 「{p}」：旧库无同名职位标题"]

    # ---------- L4 课程-技能边 ----------
    legacy_cs = {(r[0], r[1]) for r in cs}
    ok_cs = [(a, b) for a, b in legacy_cs if has_edge(a, b)]
    miss_cs = [(a, b) for a, b in legacy_cs if not has_edge(a, b)]
    # 新图中课程-技能边里，两端都是"旧库实体"但旧库没这条关系的 → 额外边
    legacy_cs_norm = {frozenset((norm(a), norm(b))) for a, b in legacy_cs}
    legacy_c_norm = {norm(c) for c in legacy_courses}
    legacy_s_all = {norm(s) for s in legacy_skills} | {norm(a) for a in alias}
    extra_cs = []
    for fs in es:
        if len(fs) != 2:
            continue
        a, b = tuple(fs)
        if (norm(a) in {norm(x) for x in new_courses} and norm(b) in legacy_s_all
                and norm(a) in legacy_c_norm and frozenset((a, b)) not in legacy_cs_norm):
            extra_cs.append((a, b))
    rep += [f"## L4 课程-技能边：旧 {len(legacy_cs)} vs 新图",
            f"- 旧关系在新图中存在：**{len(ok_cs)}/{len(legacy_cs)}**",
            f"- 缺失边（{len(miss_cs)}）：",
            "".join(f"  - {a} — {b}\n" for a, b in sorted(miss_cs)) or "  - 无",
            f"- 新图额外边（两端都是旧库实体、但旧库无此关系，{len(extra_cs)} 条）：",
            "".join(f"  - {a} — {b}\n" for a, b in sorted(extra_cs)) or "  - 无", ""]
    for a, b in sorted(miss_cs):
        checklist.append([f"{a} — {b}", "L4课程-技能边", "旧库存在此关系", "图谱中缺失", "", ""])
    for a, b in sorted(extra_cs):
        checklist.append([f"{a} — {b}", "L4课程-技能边", "旧库无此关系", "图谱中存在(待人工判断)", "", ""])

    # ---------- L5 岗位-技能边（Top 技能覆盖率） ----------
    title_skills = defaultdict(Counter)
    for r in ps:
        title_skills[norm(r[0])][r[1]] += int(r[2])
    rep += ["## L5 岗位-技能边（按职位 Top 技能覆盖）", ""]
    pos_edges = defaultdict(set)
    new_pos_norm = {norm(x) for x in new_pos}
    for fs in es:
        if len(fs) == 1:
            # 自环边：同名职位与同名技能（如「自动化测试」职位↔「自动化测试（技能）」页）
            a = tuple(fs)[0]
            if a in new_pos_norm:
                pos_edges[a].add(a)
            continue
        if len(fs) != 2:
            continue
        a, b = tuple(fs)
        if norm(a) in {norm(x) for x in new_pos}:
            pos_edges[norm(a)].add(b)
        if norm(b) in {norm(x) for x in new_pos}:
            pos_edges[norm(b)].add(a)
    total_cov = []
    for p in sorted(new_pos):
        tops = [s for s, _ in title_skills.get(norm(p), Counter()).most_common(10)]
        got = pos_edges.get(norm(p), set())
        cov = [s for s in tops if norm(s) in {norm(x) for x in got}]
        total_cov.append(len(cov) / len(tops) if tops else 0)
        miss5 = [s for s in tops if norm(s) not in {norm(x) for x in got}]
        dir_miss5 = [s for s in miss5 if s in legacy_dirs]
        real_miss5 = [s for s in miss5 if s not in legacy_dirs]
        rep += [f"### {p}（旧库 {title_count.get(p, 0)} 条记录，新图连了 {len(got)} 条技能）",
                f"- 旧库 Top10 技能：{'、'.join(tops) or '旧库无此职位'}",
                f"- 覆盖 {len(cov)}/{len(tops)}：缺 {'、'.join(miss5) or '无'}"]
        if dir_miss5:
            rep += [f"  - 其中 {'、'.join(dir_miss5)} 是 level-1 方向节点，新模型由「概念-」聚合页承载，属设计口径差异"]
        rep += [""]
        for s in miss5:
            note = "方向级关系，概念页承载(口径差异)" if s in legacy_dirs else ""
            checklist.append([f"{p} — {s}", "L5岗位-技能边", f"旧库该职位高频技能(第{tops.index(s)+1}名)", "图谱中缺失" if not note else "口径差异", note, ""])

    rep += [f"## 总体指标", "",
            f"- 课程节点召回：{len(matched_c)}/{len(legacy_courses)} = {len(matched_c)/len(legacy_courses):.0%}",
            f"- 技能节点召回(含别名)：{len(matched_s)}/{len(legacy_skills)} = {len(matched_s)/len(legacy_skills):.0%}",
            f"- 技能方向召回(level-1→概念页)：{len(dir_ok)}/{len(legacy_dirs)} = {len(dir_ok)/max(len(legacy_dirs),1):.0%}",
            f"- 课程-技能边召回：{len(ok_cs)}/{len(legacy_cs)} = {len(ok_cs)/max(len(legacy_cs),1):.0%}",
            f"- 岗位页标题可对上旧库：{len(exact)}/{len(new_pos)} = {len(exact)/max(len(new_pos),1):.0%}",
            f"- 岗位 Top10 技能平均覆盖：{sum(total_cov)/max(len(total_cov),1):.0%}", ""]

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(rep))
    with open(CSV_OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["核对对象", "层级", "基准(旧库)", "实际(新图)", "人工结论(对/错)", "备注"])
        w.writerows(checklist)

    # 控制台摘要
    print("\n".join(rep[-9:]))
    print(f"报告: {REPORT}\n清单: {CSV_OUT}（{len(checklist)} 行待人工核对）")


if __name__ == "__main__":
    main()
