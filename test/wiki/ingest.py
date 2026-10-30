# -*- coding: utf-8 -*-
"""LLM Wiki 摄取引擎 —— MediaWiki 版（简化版 Karpathy LLM Wiki 模式）。

两步链式摄取（与 nashsu/llm_wiki 同源思想）：
  Step 1 分析：LLM 读取业务数据库 -> 结构化分析（实体、概念、洞见）
  Step 2 生成：生成带 [[内部链接]] 和分类的 Wiki 页面，写入 MediaWiki

标题消歧规则（MediaWiki 一个标题只能有一个页面）：
  - 同名岗位合并为一页（列出全部公司/城市），与归档项目图谱的合并逻辑一致
  - 课程与技能重名时，课程标题追加「（课程）」后缀
LLM 不可用时自动降级为规则模式，图谱效果不受影响。
"""
import json
from collections import defaultdict
from datetime import datetime

from config import LLM_BASE_URL, LLM_ENABLED, LLM_MODEL, LLM_TIMEOUT
from mw_client import MediaWikiClient
from seed_data import fetch_all


# ---------------- LLM（OpenAI 兼容，标准库实现零依赖） ----------------
class LLMUnavailable(Exception):
    pass


def llm_chat(prompt: str) -> str:
    if not LLM_ENABLED:
        raise LLMUnavailable("LLM 未启用")
    import urllib.request
    payload = json.dumps({
        "model": LLM_MODEL, "stream": False,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{LLM_BASE_URL.rstrip('/')}/chat/completions", data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer ollama"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"].strip()
    except Exception as e:  # noqa: BLE001
        raise LLMUnavailable(str(e)) from e


# ---------------- 页面内容生成 ----------------
def course_page(c: dict, skills: list[str]) -> str:
    lines = [f"'''《{c['name']}》'''是一门{c['type']}，课程编号 {c['code']}，共 {c['credit']} 学分。", ""]
    lines += ["== 教授的技能 ==", ""]
    lines += [f"* [[{s}]]" for s in skills] or ["* 暂无"]
    lines += ["", "[[Category:课程]]"]
    return "\n".join(lines)


def skill_page(s: dict, courses: list[str], positions: list[str]) -> str:
    lines = [f"'''{s['name']}''' 属于「{s['category']}」方向（层级 {s['level']}）。", ""]
    lines += ["== 开设课程 ==", ""]
    lines += [f"* [[{c}]]" for c in courses] or ["* 暂无"]
    lines += ["", "== 岗位要求 ==", ""]
    lines += [f"* [[{p}]]" for p in positions] or ["* 暂无"]
    lines += ["", f"[[Category:技能]] [[Category:{s['category']}]]"]
    return "\n".join(lines)


def position_page(p: dict, companies: list, skills: list[str]) -> str:
    comp_txt = "、".join(f"{c}（{city}）" for c, city in companies)
    lines = [f"'''{p['title']}''' —— 招聘企业：{comp_txt}。", ""]
    lines += ["== 任职技能要求 ==", ""]
    lines += [f"* [[{s}]]" for s in skills] or ["* 暂无"]
    lines += ["", "[[Category:岗位]]"]
    return "\n".join(lines)


def concept_page(cat: str, sids: list[str], jobs: list[str], courses: list[str]) -> str:
    lines = [f"「{cat}」方向聚合了 {len(sids)} 项技能，是课程体系与岗位需求之间的桥梁。", ""]
    lines += ["== 相关技能 ==", ""] + [f"* [[{s}]]" for s in sids]
    if jobs:
        lines += ["", "== 相关岗位 ==", ""] + [f"* [[{p}]]" for p in jobs]
    if courses:
        lines += ["", "== 相关课程 ==", ""] + [f"* [[{c}]]" for c in courses]
    lines += ["", f"[[Category:概念]] [[Category:{cat}]]"]
    return "\n".join(lines)


# ---------------- 标题消歧 ----------------
def build_titles(data: dict) -> tuple[dict, dict, dict]:
    """返回 (课程标题表, 技能标题表, 岗位标题->合并信息表)。"""
    course_names = {c["name"] for c in data["courses"]}
    course_titles, skill_titles = {}, {}
    skill_name_set = {s["name"] for s in data["skills"]}
    for c in data["courses"]:
        course_titles[c["id"]] = (f"{c['name']}（课程）"
                                  if c["name"] in skill_name_set else c["name"])
    for s in data["skills"]:
        skill_titles[s["id"]] = s["name"]
    # 同名岗位合并
    positions = defaultdict(lambda: {"companies": [], "skills": set(), "id": None})
    for p in data["positions"]:
        e = positions[p["title"]]
        e["id"] = p["id"]
        e["companies"].append((p["company"], p["city"]))
    for r in data["position_skill"]:
        title = next(x["title"] for x in data["positions"] if x["id"] == r["position_id"])
        positions[title]["skills"].add(r["skill_id"])
    return course_titles, skill_titles, positions


# ---------------- 主流程 ----------------
def run_ingest(use_llm: bool | None = None) -> dict:
    data = fetch_all()
    course_titles, skill_titles, positions = build_titles(data)
    skill_name = {s["id"]: s["name"] for s in data["skills"]}

    cs_course: dict[int, list[int]] = {}
    cs_skill: dict[int, list[int]] = {}
    for r in data["course_skill"]:
        cs_course.setdefault(r["course_id"], []).append(r["skill_id"])
        cs_skill.setdefault(r["skill_id"], []).append(r["course_id"])
    ps_skill: dict[int, list[int]] = {}
    for title, e in positions.items():
        for sid in e["skills"]:
            ps_skill.setdefault(sid, []).append(title)

    # Step 1：LLM 分析（可选）
    analysis, llm_mode = "", False
    if use_llm is None:
        use_llm = LLM_ENABLED
    if use_llm:
        try:
            analysis = llm_chat(
                "以下是课程-技能-岗位数据库导出数据(JSON)。请输出结构化分析（Markdown）：\n"
                "1) 关键实体概述 2) 3~5 个跨实体知识主题 3) 数据洞见。\n\n"
                f"数据：{json.dumps(data, ensure_ascii=False)[:6000]}")
            llm_mode = True
            print("[ingest] Step1 LLM 分析完成")
        except LLMUnavailable as e:
            print(f"[ingest] LLM 不可用，降级规则模式: {e}")

    # 课程简介（LLM 模式下逐课程生成，失败留空走默认文案）
    summaries: dict[int, str] = {}
    if llm_mode:
        for c in data["courses"]:
            names = "、".join(skill_name.get(s, "?") for s in cs_course.get(c["id"], []))
            try:
                summaries[c["id"]] = llm_chat(
                    f"为课程《{c['name']}》（{c['type']}，覆盖技能：{names}）写80字以内选课介绍，只输出正文。")
            except LLMUnavailable:
                pass

    # Step 2：写页面
    mw = MediaWikiClient()
    mw.login()

    # 清理陈旧页面：数据库已不存在对应实体的旧页面自动删除
    all_titles = (set(course_titles.values()) | set(skill_titles.values())
                  | set(positions.keys()) | {"Main Page", "Wiki索引", "Wiki日志"})
    existing = {p["title"] for p in mw.all_pages_with_links()}
    cats_now = {s["category"] for s in data["skills"]}
    # MediaWiki 会将标题首字母大写（uni-app -> Uni-app），比较前统一规范化
    canon = lambda t: t[:1].upper() + t[1:]  # noqa: E731
    expected_canon = {canon(t) for t in all_titles} | {f"概念-{c}" for c in cats_now}
    stale = {t for t in existing if canon(t) not in expected_canon}
    for t in sorted(stale):
        try:
            mw.delete_page(t)
            print(f"[ingest] 已删除陈旧页面: {t}")
        except RuntimeError as e:
            print(f"[ingest] 跳过删除 [{t}]: {e}")
    n = len(stale)

    for c in data["courses"]:
        text = course_page(c, [skill_titles[s] for s in cs_course.get(c["id"], []) if s in skill_titles])
        if c["id"] in summaries:
            text = text.replace("== 教授的技能 ==",
                                f"== 简介 ==\n\n{summaries[c['id']]}\n\n== 教授的技能 ==", 1)
        mw.edit_page(course_titles[c["id"]], text)
        n += 1

    for s in data["skills"]:
        mw.edit_page(skill_titles[s["id"]], skill_page(
            s,
            [course_titles[c] for c in cs_skill.get(s["id"], []) if c in course_titles],
            sorted({t for t in ps_skill.get(s["id"], []) if t in positions})))
        n += 1

    for title, e in positions.items():
        mw.edit_page(title, position_page(
            {"title": title}, e["companies"],
            [skill_titles[s] for s in sorted(e["skills"]) if s in skill_titles]))
        n += 1

    # 概念页：按技能分类聚合
    cats: dict[str, list[int]] = {}
    for s in data["skills"]:
        cats.setdefault(s["category"], []).append(s["id"])
    concepts = 0
    for cat, sids in cats.items():
        snames = [skill_titles[i] for i in sids]
        jobs = sorted({t for i in sids for t in ps_skill.get(i, []) if t in positions})
        cnames = sorted({course_titles[c] for i in sids for c in cs_skill.get(i, []) if c in course_titles})
        mw.edit_page(f"概念-{cat}", concept_page(cat, snames, jobs, cnames))
        concepts += 1

    # 索引页
    index = ["本 Wiki 由 '''LLM Wiki 摄取引擎'''从业务数据库自动编译生成。", "",
             "== 课程 ==", ""] + [f"* [[{course_titles[c['id']]}]]" for c in data["courses"]]
    index += ["", "== 技能 ==", ""] + [f"* [[{skill_titles[s['id']]}]]" for s in data["skills"]]
    index += ["", "== 岗位 ==", ""] + [f"* [[{t}]]" for t in sorted(positions)]
    index += ["", "== 概念 ==", ""] + [f"* [[概念-{cat}]]" for cat in cats]
    index += ["", "== 分析报告 ==", ""] + (["* [[LLM分析报告]]"] if llm_mode else [])
    index += ["", "[[Category:索引]]"]
    mw.edit_page("Wiki索引", "\n".join(index))
    n += 1

    if llm_mode:
        mw.edit_page("LLM分析报告",
                     f"由 LLM 于 {datetime.now():%Y-%m-%d %H:%M:%S} 对数据库数据生成的分析：\n\n{analysis}")
        n += 1

    # 日志页（追加）
    log_line = (f"* {datetime.now():%Y-%m-%d %H:%M:%S} 摄取完成："
                f"模式={'LLM' if llm_mode else '规则'}，"
                f"课程 {len(data['courses'])}、技能 {len(data['skills'])}、"
                f"岗位 {len(positions)}（已合并同名）、概念页 {concepts}\n")
    old_text = mw.get_page_text("Wiki日志") or "本页记录 Wiki 摄取历史。\n"
    mw.edit_page("Wiki日志", old_text.rstrip() + "\n" + log_line)
    n += 1

    return {"mode": "llm" if llm_mode else "rule", "pages": n,
            "concepts": [f"概念-{c}" for c in cats], "analysis_head": analysis[:300]}


if __name__ == "__main__":
    import pprint
    pprint.pprint(run_ingest())
