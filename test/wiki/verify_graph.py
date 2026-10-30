# -*- coding: utf-8 -*-
"""图谱准确性核对工具：数据库(基准) → Wiki 页面 → 图谱 JSON 三层自动比对。

用法：
    python verify_graph.py            # 全量自动比对 + 生成人工核对清单
    python verify_graph.py --sample 30   # 指定抽检样本数（默认 30）

输出：
    1) 控制台核对报告（一致性百分比 + 差异明细）
    2) verify_report.csv —— 人工核对清单（Excel 可直接打开，含空白的「人工结论」列）

核对思路：
    基准 = SQLite 业务库（course/course_skill/position_skill，即旧项目的数据）
    中间 = MediaWiki 页面及其 [[双链]]（ingest 的产物）
    结果 = graph_data.json（前端实际渲染的图）
    节点/边每一层都可能出错：库有页无、页有图无、图多了幻觉边、边方向颠倒……
    自动比对负责找差异，人只复核「差异项 + 抽样的一致项」。
"""
import csv
import json
import os
import random
import sys

from config import GRAPH_DATA
from seed_data import fetch_all
from ingest import build_titles
from mw_client import MediaWikiClient

AUX_PAGES = {"Main Page", "沙盒测试", "Wiki索引", "Wiki日志",
             "LLM分析报告", "首页"}  # 辅助页，不计入实体核对


def norm(t: str) -> str:
    """与 MediaWiki 一致的首字母规范化。"""
    return t[:1].upper() + t[1:] if t else t


def edge_set(links: list[dict]) -> set[tuple[str, str]]:
    return {(l["source"], l["target"]) for l in links}


def has_edge(es: set, a: str, b: str) -> bool:
    return (a, b) in es or (b, a) in es  # 无向比较：力导向图不区分方向


def main(sample: int = 30) -> None:
    data = fetch_all()
    course_titles, skill_titles, positions = build_titles(data)
    skill_by_id = {s["id"]: s for s in data["skills"]}

    mw = MediaWikiClient()
    pages = {p["title"]: p for p in mw.all_pages_with_links()}
    with open(GRAPH_DATA, encoding="utf-8") as f:
        g = json.load(f)
    node_names = {n["name"] for n in g["nodes"]}
    es = edge_set(g["links"])

    # ---------- 1. 节点核对：库 → 页面 → 图 ----------
    node_rows, miss = [], []
    expect_nodes = []  # (期望标题, 类型, 来源说明)
    for cid, title in course_titles.items():
        expect_nodes.append((title, "课程", f"course.id={cid}"))
    for sid, title in skill_titles.items():
        expect_nodes.append((title, "技能", f"skill.id={sid}"))
    for title in positions:
        expect_nodes.append((title, "岗位", "position(同名合并)"))
    for cat in {s["category"] for s in data["skills"]}:
        expect_nodes.append((f"概念-{cat}", "概念", "concept page"))

    for title, typ, src in expect_nodes:
        in_page = norm(title) in pages or title in pages
        in_graph = title in node_names or norm(title) in node_names
        status = "一致" if in_page and in_graph else "缺失"
        if not in_page:
            status += "(页面无)"
        if not in_graph:
            status += "(图无)"
        node_rows.append([title, typ, src, status, "", ""])
        if status != "一致":
            miss.append((title, typ, status))

    # 图中多余节点（白名单之外、库中查无此实体的）
    expect_set = {norm(t) for t, *_ in expect_nodes}
    extra = sorted(n for n in node_names
                   if norm(n) not in expect_set and norm(n) not in AUX_PAGES
                   and not norm(n).startswith("概念-"))
    for name in extra:
        typ = next((n["type"] for n in g["nodes"] if n["name"] == name), "?")
        node_rows.append([name, typ, "图中存在/库中查无", "多余(疑似幻觉或残留)", "", ""])

    # ---------- 2. 边核对：库关系 → 图连线 ----------
    edge_rows = []
    expect_edges = []  # (a, b, 来源说明)
    for r in data["course_skill"]:
        expect_edges.append((course_titles[r["course_id"]],
                             skill_titles[r["skill_id"]],
                             f"course_skill c{r['course_id']}-s{r['skill_id']}"))
    for title, info in positions.items():
        for sid in info["skills"]:
            expect_edges.append((title, skill_titles[sid],
                                 f"position_skill {title}-s{sid}"))

    missing_edges, ok_edges = [], []
    for a, b, src in expect_edges:
        if has_edge(es, a, b):
            ok_edges.append((a, b, src))
        else:
            missing_edges.append((a, b, src))
            edge_rows.append([f"{a} — {b}", "库有/图无", src, "缺失", "", ""])

    # 图中多余边：过滤掉概念页产生的边（概念-xx 页面按设计链到该分类所有技能）
    concept_prefix = "概念-"
    extra_edges = [(l["source"], l["target"]) for l in g["links"]
                   if not has_edge(es, l["source"], l["target"])
                   and not l["source"].startswith(concept_prefix)
                   and not l["target"].startswith(concept_prefix)
                   and l["source"] not in AUX_PAGES and l["target"] not in AUX_PAGES]
    for a, b in sorted(set(extra_edges)):
        edge_rows.append([f"{a} — {b}", "图有/库无", "非概念页来源", "多余(需人工判断)", "", ""])

    # ---------- 3. 抽样：一致项中随机抽 N 条供人工复核 ----------
    random.seed(42)
    for a, b, src in random.sample(ok_edges, min(sample, len(ok_edges))):
        edge_rows.append([f"{a} — {b}", "一致(抽检)", src, "待人工确认", "", ""])

    # ---------- 4. 输出报告 ----------
    n_node = len(expect_nodes)
    n_edge = len(expect_edges)
    print("=" * 62)
    print("图谱准确性核对报告")
    print("=" * 62)
    print(f"基准：SQLite 业务库   中间：MediaWiki {len(pages)} 页   结果：图 {len(g['nodes'])} 节点 / {len(g['links'])} 边")
    print()
    print(f"[节点] 库中实体 {n_node} 个：一致 {n_node - len(miss)}，缺失/异常 {len(miss)}，图中多余 {len(extra)}")
    for t, typ, s in miss:
        print(f"   ✗ {typ}「{t}」{s}")
    for name in extra:
        print(f"   ? 多余节点「{name}」")
    print()
    print(f"[边]   库中关系 {n_edge} 条：图内一致 {len(ok_edges)}，缺失 {len(missing_edges)}，"
          f"多余(非概念页) {len(set(extra_edges))}")
    for a, b, src in missing_edges[:20]:
        print(f"   ✗ 缺失边 {a} — {b}   ({src})")
    if len(missing_edges) > 20:
        print(f"   ... 其余 {len(missing_edges) - 20} 条见 CSV")
    print()

    out = os.path.join(os.path.dirname(GRAPH_DATA), "..", "verify_report.csv")
    out = os.path.normpath(out)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["核对对象", "核对类型", "来源(基准)", "自动比对结果", "人工结论(对/错)", "备注"])
        w.writerows(node_rows)
        w.writerows(edge_rows)
    print(f"人工核对清单已生成：{out}")
    print(f"  共 {len(node_rows) + len(edge_rows)} 行 = 节点全量 {len(node_rows)} + "
          f"边差异全量 + 一致边抽检 {min(sample, len(ok_edges))} 条")
    print("  用 Excel 打开，逐行在「人工结论」列填 对/错 即可。")


if __name__ == "__main__":
    n = 30
    if "--sample" in sys.argv:
        n = int(sys.argv[sys.argv.index("--sample") + 1])
    main(n)
