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

TYPE_STYLE = {
    "课程": {"color": "#409eff", "size": 34},
    "技能": {"color": "#67c23a", "size": 20},
    "岗位": {"color": "#f56c6c", "size": 34},
    "概念": {"color": "#e6a23c", "size": 42},
    "索引": {"color": "#909399", "size": 30},
    "报告": {"color": "#b4b2a9", "size": 28},
}
DEFAULT_STYLE = {"color": "#888780", "size": 30}


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
            links.append({"source": p["title"], "target": t})
            degree[p["title"]] += 1
            degree[t] += 1

    for p in pages:
        t = node_type(p["categories"], p["title"])
        style = TYPE_STYLE.get(t, DEFAULT_STYLE)
        nodes.append({
            "name": p["title"],
            "type": t,
            "category": ", ".join(p["categories"]) or t,
            "degree": degree.get(p["title"], 0),
            "symbolSize": style["size"] + min(degree.get(p["title"], 0) * 2, 40),
            "itemStyle": {"color": style["color"]},
            "url": mw.page_url(p["title"]),
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
