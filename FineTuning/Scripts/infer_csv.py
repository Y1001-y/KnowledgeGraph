#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
用微调后的模型直接跑原始 CSV（端到端推理）

用法（WSL, venv 内）:
  python infer_csv.py                          # 默认原始数据前 10 条
  python infer_csv.py --n 50                   # 前 50 条
  python infer_csv.py --start 100 --n 20       # 从第 101 条开始，跑 20 条
  python infer_csv.py --csv 其他.csv --n 10

输出:
  FineTuning/Outputs/predict/预测结果_前{N}条.xlsx (+ 同名 .csv)
  控制台同时打印对照表（模型预测 vs 词典抽取）
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--csv", default="/mnt/d/study/KnowledgeGraph/Origin data/3月新增-江苏-互联网AI.csv")
ap.add_argument("--n", type=int, default=10, help="跑多少条")
ap.add_argument("--start", type=int, default=0, help="从第几条开始（0 表示第1条）")
ap.add_argument("--adapter", default="/mnt/d/study/KnowledgeGraph/FineTuning/Outputs/qwen3-8b-skills-lora/final")
ap.add_argument("--out", default="/mnt/d/study/KnowledgeGraph/FineTuning/Outputs/predict")
ap.add_argument("--max-new", type=int, default=128)
ap.add_argument("--jd-chars", type=int, default=1200, help="JD 截断长度，必须与训练一致")
args = ap.parse_args()

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import pandas as pd
import torch

# ---------- 1. 读原始 CSV 的前 N 条 ----------
print(f"读取数据: {args.csv}")
df = pd.read_csv(args.csv, dtype=str)
sub = df.iloc[args.start: args.start + args.n]
print(f"总行数 {len(df)}，本次推理 {len(sub)} 条（第 {args.start+1} ~ {args.start+len(sub)} 条）")

# ---------- 2. 加载模型 + adapter ----------
from unsloth import FastLanguageModel

print(f"加载 adapter: {args.adapter}")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=args.adapter,        # adapter 目录，自动挂回底座
    max_seq_length=1024,
    dtype=None,
    load_in_4bit=True,
    use_exact_model_name=True,
    local_files_only=True,
)
FastLanguageModel.for_inference(model)

INSTRUCTION = "从下面的岗位信息中提取所有要求掌握的技术技能，只输出技能名称，用、分隔。"


def build_input(row) -> tuple[str, str]:
    """与训练脚本完全一致的输入构造方式"""
    def sval(col):
        v = row.get(col)
        return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
    job = sval("jobInfo_jobName").strip()
    pos = sval("jobInfo_positionName").strip()
    jd = sval("jobInfo_postDescription").strip()[: args.jd_chars]
    return job, f"岗位名称：{job}\n职位类别：{pos}\n岗位描述：{jd}"


def generate(prompt_input: str) -> str:
    msgs = [{"role": "user", "content": f"{INSTRUCTION}\n\n{prompt_input}"}]
    ids = tokenizer.apply_chat_template(
        msgs, add_generation_prompt=True, return_tensors="pt", enable_thinking=False
    ).to("cuda")
    with torch.no_grad():
        out = model.generate(
            input_ids=ids, max_new_tokens=args.max_new, do_sample=False,
            temperature=None, top_p=None, repetition_penalty=1.15,
            pad_token_id=tokenizer.eos_token_id,
        )
    text = tokenizer.decode(out[0][ids.shape[1]:], skip_special_tokens=True).strip()
    # 清理复读与多余符号
    parts, seen = [], set()
    for p in re.split(r"[、,，;；\n]+", text):
        p = p.strip().strip("'\"“”‘’。. ")
        if p and p not in seen and len(p) <= 20:
            seen.add(p)
            parts.append(p)
    return "、".join(parts)


# ---------- 3. 逐条推理 ----------
rows = []
for i, (_, row) in enumerate(sub.iterrows(), 1):
    job, inp = build_input(row)
    pred = generate(inp)
    rows.append({
        "序号": args.start + i,
        "岗位名称": job,
        "职位类别": row.get("jobInfo_positionName", ""),
        "城市": row.get("jobInfo_locationName", ""),
        "薪资": row.get("jobInfo_salaryDesc", ""),
        "经验": row.get("jobInfo_experienceName", ""),
        "学历": row.get("jobInfo_degreeName", ""),
        "模型预测技能": pred,
        "预测技能数": len([x for x in pred.split("、") if x]),
        "JD前80字": str(row.get("jobInfo_postDescription", ""))[:80].replace("\n", " "),
    })
    print(f"\n[{args.start + i}] {job} | {row.get('jobInfo_salaryDesc', '')} | {row.get('jobInfo_locationName', '')}")
    print(f"    预测: {pred}")

# ---------- 4. 落盘 ----------
# 带时间戳：避免目标文件正被 Excel/预览打开而锁定(PermissionError)导致保存失败
from datetime import datetime

out_dir = Path(args.out)
out_dir.mkdir(parents=True, exist_ok=True)
out_df = pd.DataFrame(rows)
stamp = datetime.now().strftime("%m%d_%H%M%S")
base = out_dir / f"预测结果_前{args.start + len(sub)}条_{stamp}"
try:
    with pd.ExcelWriter(base.with_suffix(".xlsx"), engine="xlsxwriter") as w:
        out_df.to_excel(w, index=False, sheet_name="预测")
    saved = base.with_suffix(".xlsx")
except ImportError:
    saved = base.with_suffix(".csv")
    print("未安装 xlsxwriter，已改写 CSV")
except PermissionError:
    saved = base.with_suffix(".csv")
    print("xlsx 被占用(文件开着?)，已改写 CSV")
out_df.to_csv(base.with_suffix(".csv"), index=False, encoding="utf-8-sig")

print("\n" + "=" * 60)
print(f"结果已保存: {saved}")
print(f"平均每条抽出技能数: {out_df['预测技能数'].mean():.1f}")
print("完成 ✅")
