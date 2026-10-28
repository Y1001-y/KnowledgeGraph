#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SFT 训练数据体检

用法: python audit_data.py
检查项:
  1. JSON 合法性、字段完整性
  2. 标签噪声（非技能词、空标签、重复标签）
  3. 训练/测试集泄漏（同岗位跨集）
  4. 截断导致的"标签不可见"（标答里的技能在输入里找不到）
  5. 标签数量分布、超长样本
  6. 输入文本异常（空、超短、乱码）
  7. 重复样本
  8. 长尾技能分布
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from prepare_dataset import SKILLS, INSTRUCTION, build_matchers, extract_skills  # noqa: E402

DATA = Path(r"D:\study\KnowledgeGraph\FineTuning\Datasets\Processed")
TRAIN = DATA / "训练集" / "train_sft_技能抽取.jsonl"
TEST = DATA / "测试集" / "test_sft_技能抽取.jsonl"

matchers = build_matchers()
CANON = {s for s, _ in SKILLS}

# 明显非技能的噪声词（曾出现在平台标签里）
JUNK = ["工作简单", "可带手机", "环境好", "氛围", "五险", "双休", "包吃", "包住",
        "不加班", "接受出差", "不限", "nan", "None", "无"]


def load(p: Path):
    rows, bad = [], 0
    with open(p, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            rows.append(o)
    return rows, bad


def jd_of(input_text: str) -> str:
    m = re.search(r"岗位描述：(.*)", input_text, re.S)
    return m.group(1) if m else input_text


def audit(name: str, rows: list[dict], bad: int):
    print("\n" + "=" * 72)
    print(f"【{name}】样本数 = {len(rows)}" + (f"，JSON 损坏 {bad} 行" if bad else ""))
    print("=" * 72)
    issues = []

    # 1. 字段完整性 / instruction 一致性
    miss = sum(1 for r in rows if not all(k in r for k in ("instruction", "input", "output")))
    diff_instr = sum(1 for r in rows if r.get("instruction") != INSTRUCTION)
    print(f"1. 字段缺失: {miss} | instruction 与标准不一致: {diff_instr}")
    if miss or diff_instr:
        issues.append("字段/指令不一致")

    # 2. 标签质量
    empty_lab = 0
    noncanon = Counter()
    dup_in_out = 0
    junk_hit = Counter()
    lab_counts = []
    for r in rows:
        labels = [x for x in re.split(r"[、,，]+", r["output"]) if x.strip()]
        if not labels:
            empty_lab += 1
        lab_counts.append(len(labels))
        if len(labels) != len(set(labels)):
            dup_in_out += 1
        for lb in labels:
            lb = lb.strip()
            if lb not in CANON:
                noncanon[lb] += 1
            for j in JUNK:
                if j in lb:
                    junk_hit[lb] += 1
    print(f"2. 空标签样本: {empty_lab} | 标签内有重复: {dup_in_out}")
    print(f"   非规范技能名(不在词典): {len(noncanon)} 种 / {sum(noncanon.values())} 次"
          + (f" -> Top: {noncanon.most_common(8)}" if noncanon else " ✅"))
    print(f"   含噪声词(工作简单/五险等): {sum(junk_hit.values())} 次"
          + (f" -> {junk_hit.most_common(5)}" if junk_hit else " ✅ 无"))
    if empty_lab or noncanon or junk_hit:
        issues.append("标签含非技能/非规范内容")

    # 3. 截断导致的标签不可见（用完整 input 判定，含岗位名称，与抽标签口径一致）
    invisible = Counter()
    inv_samples = 0
    for r in rows:
        visible = set(extract_skills(r["input"], matchers))
        labels = {x.strip() for x in re.split(r"[、,，]+", r["output"]) if x.strip()}
        missing = labels - visible
        if missing:
            inv_samples += 1
            for m in missing:
                invisible[m] += 1
    pct = inv_samples / len(rows) * 100 if rows else 0
    print(f"3. 标答技能在输入中不可见(被截断/误标): {inv_samples} 条 ({pct:.1f}%)"
          + (f" -> Top: {invisible.most_common(6)}" if invisible else " ✅ 无"))
    if pct > 5:
        issues.append(f"{pct:.1f}% 样本标签超出输入可见范围(JD 截断 1200 字符导致)")

    # 4. 标签数量分布
    if lab_counts:
        s = sorted(lab_counts)
        n = len(s)
        print(f"4. 每样本技能数: 平均 {sum(s)/n:.1f} | 中位 {s[n//2]} | 最大 {s[-1]} | "
              f"1个占比 {sum(1 for x in s if x == 1)/n*100:.1f}%")
        odd = sum(1 for x in s if x > 20)
        if odd:
            print(f"   技能数 >20 的异常样本: {odd} 条（可能 JD 是技能清单堆砌）")

    # 5. 重复样本
    exact = len(rows) - len({(r["input"], r["output"]) for r in rows})
    dup_in = len(rows) - len({r["input"] for r in rows})
    print(f"5. 完全重复样本: {exact} | 同输入不同答案: {dup_in}"
          + (" ✅" if exact == 0 and dup_in == 0 else " ⚠️"))
    if exact or dup_in:
        issues.append("存在重复样本")

    # 6. 输入异常
    short = sum(1 for r in rows if len(jd_of(r["input"])) < 30)
    mojibake = sum(1 for r in rows if "ï¿½" in r["input"] or "\ufffd" in r["input"])
    print(f"6. JD 过短(<30字): {short} | 含乱码: {mojibake}")
    if mojibake:
        issues.append("存在乱码")
    return rows, issues, lab_counts


train_rows, bad1 = load(TRAIN)
test_rows, bad2 = load(TEST)
tr, iss_tr, _ = audit("训练集", train_rows, bad1)
te, iss_te, _ = audit("测试集", test_rows, bad2)

# 7. 泄漏检查
print("\n" + "=" * 72)
print("【训练/测试泄漏检查】")
print("=" * 72)
tr_jd = {jd_of(r["input"]) for r in tr}
te_jd = {jd_of(r["input"]) for r in te}
overlap = tr_jd & te_jd
print(f"7. 同一份 JD 同时出现在训练集和测试集: {len(overlap)} 条"
      + (" ✅ 无泄漏" if not overlap else " ⚠️ 存在泄漏，评估指标会虚高"))
if overlap:
    print("   示例:", list(overlap)[0][:80].replace("\n", " "))
    iss_te.append("训练/测试 JD 重叠")

# 8. 长尾
print("\n" + "=" * 72)
print("【长尾技能分布】")
print("=" * 72)
cnt = Counter()
for r in tr:
    for x in re.split(r"[、,，]+", r["output"]):
        if x.strip():
            cnt[x.strip()] += 1
once = sum(1 for v in cnt.values() if v == 1)
print(f"8. 训练集中出现过的技能: {len(cnt)} 种 | 仅出现1次的: {once} 种")
print("   Top10:", "、".join(f"{k}({v})" for k, v in cnt.most_common(10)))
print("   罕见(<3次):", "、".join(list(k for k, v in cnt.items() if v < 3)[:15]))

print("\n" + "=" * 72)
print("结论")
print("=" * 72)
all_issues = iss_tr + iss_te
if all_issues:
    for i in set(all_issues):
        print(f"  ⚠️ {i}")
else:
    print("  ✅ 未发现明显问题")
