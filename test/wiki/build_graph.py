# -*- coding: utf-8 -*-
"""图谱构建器：从 MediaWiki API 拉取全部页面及其 [[内部链接]]，
生成 ECharts 力导向图所需 nodes/links/categories，写入 graph_data.json。

图谱不是手工配置的——页面间的 [[双链]] 就是边，分类就是节点颜色，
这正是「LLM Wiki 模式」：图谱从 Wiki 内容中自动涌现。
"""
import json
import os
from urllib.parse import quote

from config import GRAPH_DATA
from mw_client import MediaWikiClient
from seed_data import load_snapshot

TYPE_STYLE = {
    "课程": {"color": "#409eff", "size": 34},
    "技能": {"color": "#67c23a", "size": 20},
    "岗位": {"color": "#f56c6c", "size": 34},
    "概念": {"color": "#e6a23c", "size": 42},
    "索引": {"color": "#909399", "size": 30},
    "报告": {"color": "#b4b2a9", "size": 28},
}
DEFAULT_STYLE = {"color": "#888780", "size": 30}

# 边的语义标注（源类型, 目标类型) -> 关系名，用于 tooltip 与连线配色
REL_NAMES = {
    ("课程", "技能"): "教授", ("技能", "课程"): "开设于",
    ("岗位", "技能"): "要求", ("技能", "岗位"): "任职方向",
    ("概念", "技能"): "聚合", ("概念", "课程"): "相关课程",
    ("概念", "岗位"): "相关岗位", ("索引", "课程"): "收录",
    ("索引", "技能"): "收录", ("索引", "岗位"): "收录",
    ("索引", "概念"): "收录",
}
REL_COLORS = {"教授": "#409eff", "要求": "#f56c6c", "聚合": "#e6a23c"}


def snapshot_info() -> tuple[dict, dict, dict]:
    """从数据快照提取节点标注信息（仅用于前端展示，不影响图谱结构）。"""
    snap = load_snapshot()
    skill_names = {s["name"] for s in snap["skills"]}
    position_titles = {p["title"] for p in snap["positions"]}
    # 与 ingest.build_titles 保持一致的消歧后缀规则
    course_info = {c["name"] + ("（课程）" if c["name"] in skill_names
                                or c["name"] in position_titles else ""): c
                   for c in snap["courses"]}
    skill_info = {s["name"]: s for s in snap["skills"]}
    pos_info: dict[str, dict] = {}
    for p in snap["positions"]:
        e = pos_info.setdefault(p["title"], {"recs": 0, "smin": 0, "smax": 0})
        e["recs"] = p.get("recs") or e["recs"]
        e["smin"] = p.get("salary_min") or e["smin"]
        e["smax"] = p.get("salary_max") or e["smax"]
    return course_info, skill_info, pos_info


def node_annotation(t: str, name: str,
                    course_info: dict, skill_info: dict, pos_info: dict) -> dict:
    extra = {}
    if t == "课程" and name in course_info:
        c = course_info[name]
        extra = {"teacher": c.get("teacher", ""), "credit": c.get("credit", 0),
                 "desc": (c.get("description", "") or "")[:60]}
    elif t == "技能":
        bare = name[:-4] if name.endswith("（技能）") else name  # 剥掉消歧后缀
        if bare in skill_info:
            s = skill_info[bare]
            extra = {"direction": s["category"],
                     "aliases": s.get("aliases") if isinstance(s.get("aliases"), list) else []}
    elif t == "概念" and name.startswith("概念-"):
        extra = {"direction": name[3:]}
    elif t == "岗位" and name in pos_info:
        e = pos_info[name]
        extra = {"recs": e["recs"], "smin": e["smin"], "smax": e["smax"]}
    return extra


def node_type(categories: list[str], title: str) -> str:
    for c in categories:
        if c in TYPE_STYLE:
            return c
    if title.startswith("概念-"):
        return "概念"
    if "LLM" in title or "分析" in title:
        return "报告"
    return "其他"


def build_graph() -> dict:
    mw = MediaWikiClient()
    pages = mw.all_pages_with_links()
    course_info, skill_info, pos_info = snapshot_info()

    type_of = {p["title"]: node_type(p["categories"], p["title"]) for p in pages}
    titles = {p["title"] for p in pages}
    degree = {p["title"]: 0 for p in pages}
    nodes, links, seen = [], [], set()

    for p in pages:
        for t in p["links"]:
            if t not in titles:          # 红链（页面不存在）跳过
                continue
            key = (p["title"], t)
            if key in seen:
                continue
            seen.add(key)
            rel = REL_NAMES.get((type_of[p["title"]], type_of[t]), "引用")
            links.append({"source": p["title"], "target": t, "rel": rel,
                          "lineStyle": {"color": REL_COLORS.get(rel, "#c0c4cc")}})
            degree[p["title"]] += 1
            degree[t] += 1

    for p in pages:
        t = type_of[p["title"]]
        style = TYPE_STYLE.get(t, DEFAULT_STYLE)
        nodes.append({
            "name": p["title"],
            "type": t,
            "category": ", ".join(p["categories"]) or t,
            "degree": degree.get(p["title"], 0),
            "symbolSize": style["size"] + min(degree.get(p["title"], 0) * 2, 40),
            "itemStyle": {"color": style["color"]},
            "url": mw.page_url(p["title"]),
            **node_annotation(t, p["title"], course_info, skill_info, pos_info),
        })

    categories = [{"name": k, "itemStyle": {"color": v["color"]}} for k, v in TYPE_STYLE.items()]
    result = {
        "nodes": nodes, "links": links, "categories": categories,
        "stats": {"nodeCount": len(nodes), "linkCount": len(links),
                  "byType": {k: sum(1 for n in nodes if n["type"] == k) for k in TYPE_STYLE}},
    }
    os.makedirs(os.path.dirname(GRAPH_DATA), exist_ok=True)
    with open(GRAPH_DATA, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"图谱数据已生成: {GRAPH_DATA}  节点 {len(nodes)}  边 {len(links)}")
    # 前端源码（web/）部署到站点根目录，保证页面与数据版本一致
    try:
        import deploy_static
        deploy_static.deploy()
    except Exception as e:  # 部署失败不影响图谱数据本身
        print(f"[警告] 前端资源部署失败：{e}")
    return result


if __name__ == "__main__":
    build_graph()
