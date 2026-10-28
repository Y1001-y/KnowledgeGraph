#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
微调后模型批量评估：在测试集上算技能抽取的 P/R/F1

用法（WSL, venv 内）:
  python eval_sft.py                     # 默认评估 200 条（约10分钟）
  python eval_sft.py --limit 0           # 全量 739 条（约30-40分钟）
  python eval_sft.py --adapter 其他adapter路径

输出:
  FineTuning/Outputs/eval/
    样本级明细.xlsx    每条样本的预测/标准答案/P/R/F1
    技能级报表.xlsx    每种技能的 命中/误报/漏报 次数
    summary.json      汇总指标
"""
import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

import torch

ap = argparse.ArgumentParser()
ap.add_argument("--adapter", default="/mnt/d/study/KnowledgeGraph/FineTuning/Outputs/qwen3-8b-skills-lora/final")
ap.add_argument("--test", default="/mnt/d/study/KnowledgeGraph/FineTuning/Datasets/Processed/测试集/test_sft_技能抽取.jsonl")
ap.add_argument("--out", default="/mnt/d/study/KnowledgeGraph/FineTuning/Outputs/eval")
ap.add_argument("--limit", type=int, default=200, help="评估条数，0=全部")
ap.add_argument("--max-new", type=int, default=96)
args = ap.parse_args()

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# ---------------- 加载 adapter（自动挂回底座） ----------------
from unsloth import FastLanguageModel

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=args.adapter,       # adapter 目录，unsloth 会按 adapter_config 自动找底座
    max_seq_length=1024,
    dtype=None,
    load_in_4bit=True,
    use_exact_model_name=True,
    local_files_only=True,
)
FastLanguageModel.for_inference(model)

# ---------------- 读测试集 ----------------
samples = []
with open(args.test, encoding="utf-8") as f:
    for line in f:
        samples.append(json.loads(line))
if args.limit > 0:
    samples = samples[:args.limit]
print(f"评估样本数: {len(samples)}")


def parse_skills(s: str) -> list[str]:
    """把 'A、B、C' 或逗号分隔的输出解析成集合，去掉杂字符"""
    s = s.strip().strip("'\"“”‘’。.")
    parts = re.split(r"[、,，;；\n]+", s)
    out = []
    for p in parts:
        p = p.strip().strip("'\"“”‘’。. ")
        if p and p not in out and len(p) <= 20:   # 过滤复读/超长垃圾
            out.append(p)
    return out


# ---------------- 批量推理 ----------------
rows = []
skill_tp, skill_fp, skill_fn = Counter(), Counter(), Counter()
gold_counter = Counter()

for i, s in enumerate(samples):
    msgs = [{"role": "user", "content": f"{s['instruction']}\n\n{s['input']}"}]
    inputs = tokenizer.apply_chat_template(
        msgs, add_generation_prompt=True, return_tensors="pt", enable_thinking=False
    ).to("cuda")
    with torch.no_grad():
        out = model.generate(input_ids=inputs, max_new_tokens=args.max_new,
                             do_sample=False, temperature=None, top_p=None,
                             repetition_penalty=1.15,
                             pad_token_id=tokenizer.eos_token_id)
    raw_pred = tokenizer.decode(out[0][inputs.shape[1]:], skip_special_tokens=True)
    pred = set(parse_skills(raw_pred))
    gold = set(parse_skills(s["output"]))
    for g in gold:
        gold_counter[g] += 1

    tp = pred & gold
    fp, fn = pred - gold, gold - pred
    for t in tp:
        skill_tp[t] += 1
    for t in fp:
        skill_fp[t] += 1
    for t in fn:
        skill_fn[t] += 1

    p = len(tp) / len(pred) if pred else 0.0
    r = len(tp) / len(gold) if gold else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    rows.append({"序号": i + 1,
                 "预测": "、".join(sorted(pred)),
                 "标准答案": "、".join(sorted(gold)),
                 "命中数": len(tp), "误报数": len(fp), "漏报数": len(fn),
                 "Precision": round(p, 3), "Recall": round(r, 3), "F1": round(f1, 3)})
    if (i + 1) % 20 == 0:
        done_f1 = sum(r_["F1"] for r_ in rows) / len(rows)
        print(f"  进度 {i+1}/{len(samples)} | 当前平均F1: {done_f1:.3f}")

# ---------------- 汇总 ----------------
import pandas as pd

n = len(rows)
micro_p = sum(r_["命中数"] for r_ in rows) / max(1, sum(r_["命中数"] + r_["误报数"] for r_ in rows))
micro_r = sum(r_["命中数"] for r_ in rows) / max(1, sum(r_["命中数"] + r_["漏报数"] for r_ in rows))
micro_f1 = 2 * micro_p * micro_r / (micro_p + micro_r) if (micro_p + micro_r) else 0.0
macro_f1 = sum(r_["F1"] for r_ in rows) / n
exact = sum(1 for r_ in rows if r_["误报数"] == 0 and r_["漏报数"] == 0) / n

summary = {
    "样本数": n,
    "Micro-P": round(micro_p, 4), "Micro-R": round(micro_r, 4), "Micro-F1": round(micro_f1, 4),
    "Macro-F1": round(macro_f1, 4),
    "完全匹配率": round(exact, 4),
}
print("\n" + "=" * 60)
for k, v in summary.items():
    print(f"  {k:<12}: {v}")

# ---------------- 技能级报表 ----------------
all_skills = set(skill_tp) | set(skill_fp) | set(skill_fn)
skill_rows = [{
    "技能": s,
    "标准答案中出现": gold_counter.get(s, 0),
    "命中": skill_tp.get(s, 0),
    "误报": skill_fp.get(s, 0),
    "漏报": skill_fn.get(s, 0),
} for s in all_skills]
skill_df = pd.DataFrame(skill_rows)
skill_df["Precision"] = (skill_df["命中"] / (skill_df["命中"] + skill_df["误报"]).replace(0, 1)).round(3)
skill_df["Recall"] = (skill_df["命中"] / (skill_df["命中"] + skill_df["漏报"]).replace(0, 1)).round(3)
skill_df = skill_df.sort_values(["标准答案中出现", "误报"], ascending=False).reset_index(drop=True)

# ---------------- 落盘 ----------------
# WSL venv 可能没装 xlsxwriter：优先 xlsxwriter，退而 openpyxl，再退 csv
def pick_engine() -> str:
    for eng in ("xlsxwriter", "openpyxl"):
        try:
            __import__(eng)
            return eng
        except ImportError:
            continue
    return "csv"

out_dir = Path(args.out)
out_dir.mkdir(parents=True, exist_ok=True)
detail_df = pd.DataFrame(rows)
engine = pick_engine()
if engine == "csv":
    detail_df.to_csv(out_dir / "样本级明细.csv", index=False, encoding="utf-8-sig")
    skill_df.to_csv(out_dir / "技能级报表.csv", index=False, encoding="utf-8-sig")
    print("未安装 xlsxwriter/openpyxl，已改写 CSV")
else:
    with pd.ExcelWriter(out_dir / "样本级明细.xlsx", engine=engine) as w:
        detail_df.to_excel(w, index=False, sheet_name="样本")
    with pd.ExcelWriter(out_dir / "技能级报表.xlsx", engine=engine) as w:
        skill_df.to_excel(w, index=False, sheet_name="技能")
with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

print(f"\nTop 误报技能 (模型多答的):\n{skill_df.nlargest(10, '误报')[['技能', '误报']].to_string(index=False)}")
print(f"\nTop 漏报技能 (模型漏掉的):\n{skill_df.nlargest(10, '漏报')[['技能', '漏报']].to_string(index=False)}")
print(f"\n报表已保存: {out_dir}")
print("评估完成 ✅")
