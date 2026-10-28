#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Qwen3-8B QLoRA 微调：岗位JD -> 技术技能抽取
Unsloth + bitsandbytes 4bit，适配 RTX 5070 Ti 12GB / WSL2

数据: Alpaca 格式 jsonl (instruction/input/output)，来自 prepare_dataset.py
输出: LoRA adapter 到 FineTuning/Outputs/

用法（WSL, venv 内）:
  python train_sft.py --max-steps 20      # 冒烟测试，20步验证链路
  python train_sft.py --epochs 1          # 正式训练 1 轮（约1-2小时）
  python train_sft.py                     # 默认 3 轮（README 基线）
  python train_sft.py --resume <ckpt目录>  # 断点续训
"""
import argparse
import json
import os
import random
from pathlib import Path

import torch
from datasets import load_dataset
from trl import SFTConfig, SFTTrainer

# ---------------- 参数 ----------------
ap = argparse.ArgumentParser()
ap.add_argument("--model", default="/home/yy/unsloth-work/models/Qwen3-8B-unsloth-bnb-4bit")
ap.add_argument("--data", default="/mnt/d/study/KnowledgeGraph/FineTuning/Datasets/Processed/训练集/train_sft_技能抽取.jsonl")
ap.add_argument("--test", default="/mnt/d/study/KnowledgeGraph/FineTuning/Datasets/Processed/测试集/test_sft_技能抽取.jsonl")
ap.add_argument("--output", default="/mnt/d/study/KnowledgeGraph/FineTuning/Outputs/qwen3-8b-skills-lora")
ap.add_argument("--epochs", type=int, default=3)
ap.add_argument("--max-steps", type=int, default=-1, help=">0 时只跑这么多步（冒烟测试）")
ap.add_argument("--max-seq", type=int, default=1024)
ap.add_argument("--bs", type=int, default=1, help="per_device_train_batch_size")
ap.add_argument("--accum", type=int, default=8, help="gradient_accumulation_steps")
ap.add_argument("--lr", type=float, default=2e-4)
ap.add_argument("--lora-r", type=int, default=16)
ap.add_argument("--lora-alpha", type=int, default=32)
ap.add_argument("--resume", default=None, help="checkpoint 目录，断点续训")
args = ap.parse_args()

os.environ.setdefault("HF_HUB_OFFLINE", "1")   # 全程本地，禁止联网探测
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

random.seed(3407)

# ---------------- 1. 加载模型 ----------------
from unsloth import FastLanguageModel
from unsloth.chat_templates import train_on_responses_only

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=args.model,
    max_seq_length=args.max_seq,
    dtype=None,
    load_in_4bit=True,
    use_exact_model_name=True,
    local_files_only=True,
)

# LoRA 挂载：r/alpha 按 README 基线，覆盖所有线性层
model = FastLanguageModel.get_peft_model(
    model,
    r=args.lora_r,
    lora_alpha=args.lora_alpha,
    lora_dropout=0,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    bias="none",
    use_gradient_checkpointing="unsloth",   # Unsloth 优化版省显存
    random_state=3407,
    max_seq_length=args.max_seq,
)

# ---------------- 2. 数据 ----------------
dataset = load_dataset("json", data_files=args.data, split="train")

def to_text(example):
    """用 Qwen3 官方 chat template 组装训练文本；enable_thinking=False 跳过思考段"""
    messages = [
        {"role": "user", "content": f"{example['instruction']}\n\n{example['input']}"},
        {"role": "assistant", "content": example["output"]},
    ]
    text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False, enable_thinking=False
    )
    if not text.endswith(tokenizer.eos_token):
        text += tokenizer.eos_token
    return {"text": text}

dataset = dataset.map(to_text, remove_columns=dataset.column_names)
print(dataset)
print("--- 样例 ---")
print(dataset[0]["text"][:400])

# ---------------- 3. 训练器 ----------------
# 兼容任意版本 TRL/transformers：用 dataclass 字段做白名单过滤，
# 被改名/移除的参数(如 warmup_ratio、max_seq_length、tokenizer)自动降级或剔除
import dataclasses

sft_fields = {f.name for f in dataclasses.fields(SFTConfig)}
seq_key = "max_seq_length" if "max_seq_length" in sft_fields else "max_length"
tok_key = "tokenizer" if "tokenizer" in sft_fields else "processing_class"

candidate: dict = {
    "dataset_text_field": "text",
    seq_key: args.max_seq,
    "per_device_train_batch_size": args.bs,
    "gradient_accumulation_steps": args.accum,
    "num_train_epochs": args.epochs,
    "max_steps": args.max_steps,
    "learning_rate": args.lr,
    "lr_scheduler_type": "cosine",
    "logging_steps": 10,
    "save_strategy": "steps" if args.max_steps <= 0 else "no",
    "save_steps": 500,
    "output_dir": args.output,
    "optim": "adamw_8bit",           # 省显存
    "seed": 3407,
    "report_to": "none",
    "dataset_num_proc": 4,
}
# 预热：新版可能没有 warmup_ratio，退化为固定 warmup_steps
if "warmup_ratio" in sft_fields:
    candidate["warmup_ratio"] = 0.03
elif "warmup_steps" in sft_fields:
    candidate["warmup_steps"] = 30
# 这些参数若被新版移除则自动丢弃
for k in ("weight_decay", "save_total_limit"):
    if k in sft_fields:
        candidate[k] = {"weight_decay": 0.01, "save_total_limit": 2}[k]

trainer = SFTTrainer(
    model=model,
    train_dataset=dataset,
    args=SFTConfig(**candidate),
    **{tok_key: tokenizer},
)
print(f"TRL 兼容: 序列长度参数={seq_key}, 分词器参数={tok_key}")

# 只对 assistant 回复部分计算 loss（技能标签），不学 JD 本身
trainer = train_on_responses_only(
    trainer,
    instruction_part="<|im_start|>user\n",
    response_part="<|im_start|>assistant\n",
)

# ---------------- 4. 显存基线 ----------------
gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
print(f"\nGPU 总显存: {gpu_mem:.2f} GB | 训练前已用: "
      f"{torch.cuda.memory_reserved()/1024**3:.2f} GB")

# ---------------- 5. 训练 ----------------
train_result = trainer.train(resume_from_checkpoint=args.resume)
metrics = train_result.metrics
trainer.log_metrics("train", metrics)
trainer.save_metrics("train", metrics)
trainer.save_state()

final_dir = os.path.join(args.output, "final")
trainer.save_model(final_dir)          # LoRA adapter
tokenizer.save_pretrained(final_dir)
print(f"\nLoRA adapter 已保存: {final_dir}")

# ---------------- 6. 训练后冒烟验证：抽 3 条测试集对比 ----------------
FastLanguageModel.for_inference(model)
test_samples = []
with open(args.test, encoding="utf-8") as f:
    for line in f:
        test_samples.append(json.loads(line))
        if len(test_samples) >= 3:
            break

print("\n" + "=" * 70)
print("训练后验证（测试集前3条）")
print("=" * 70)
for i, s in enumerate(test_samples, 1):
    msgs = [{"role": "user", "content": f"{s['instruction']}\n\n{s['input']}"}]
    inputs = tokenizer.apply_chat_template(
        msgs, add_generation_prompt=True, return_tensors="pt", enable_thinking=False
    ).to("cuda")
    with torch.no_grad():
        out = model.generate(input_ids=inputs, max_new_tokens=128,
                             do_sample=False, temperature=None, top_p=None,
                             repetition_penalty=1.15)  # 抑制欠训练阶段的复读循环
    pred = tokenizer.decode(out[0][inputs.shape[1]:], skip_special_tokens=True).strip()
    print(f"\n[{i}] 预测: {pred[:150]}")
    print(f"    标准答案: {s['output'][:150]}")

print(f"\n峰值显存: {torch.cuda.max_memory_reserved()/1024**3:.2f} GB")
print("训练完成 ✅")
