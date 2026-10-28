# FineTuning

模型微调模块。基于 Unsloth + QLoRA 微调 Qwen3-8B，实现「岗位 JD → 技术技能抽取」，
并产出江苏互联网 AI 岗位市场的技能需求统计。

## 目录说明

| 目录 | 用途 | 是否提交 |
|---|---|---|
| `config/` | 超参配置（yaml） | 是 |
| `Datasets/Raw/` | 原始数据集（大文件，本地存放） | 否，仅保留 .gitkeep |
| `Datasets/Processed/` | 处理后的训练/测试集与技能统计 | 否（可由脚本重建），仅保留 .gitkeep |
| `Datasets/Samples/` | 脱敏小样本（格式参考） | 是 |
| `Scripts/` | 数据准备、训练、评估、推理脚本 | 是 |
| `Notebooks/` | 实验用 notebook | 是 |
| `Outputs/` | 训练产物（LoRA 权重、评估报表、预测结果） | 否，仅保留 .gitkeep |
| `Docs/` | 训练记录与踩坑笔记 | 是 |

## 任务定义

```
输入: 岗位名称 + 职位类别 + 岗位描述(JD 前 1200 字符)
输出: 该岗位要求的技术技能列表（顿号分隔，如 Java、MySQL、Redis）
```

技能标签由 `Scripts/prepare_dataset.py` 内置的 130+ 条正则词典（覆盖编程语言、
前端、后端框架、数据库、大数据、AI、运维、测试、嵌入式）从 JD 中抽取生成。

## 运行环境

- WSL2 Ubuntu + RTX 5070 Ti Laptop 12GB（sm_120，需 torch 2.7+ / cu128）
- Python 3.12 venv：`/home/yy/unsloth-work/.venv`
- 关键依赖：unsloth、trl、transformers 5.x、datasets（国内 pip 装 xlsxwriter 需镜像）

## 使用流程

```bash
source /home/yy/unsloth-work/.venv/bin/activate
cd /mnt/d/study/KnowledgeGraph/FineTuning/Scripts

# 1. 模型加载自检（首次必跑）
python test_load.py

# 2. 数据准备：清洗 -> 去重 -> 划分 -> 技能抽取 -> SFT jsonl + 双口径统计
python prepare_dataset.py                 # --n 1000 控制测试集行数

# 3. 数据体检（8 维度，改数据后必跑，30 秒）
python audit_data.py

# 4. 训练（QLoRA）
python train_sft.py --epochs 1            # --max-steps 20 冒烟；--resume 断点续训

# 5. 评估：测试集 P/R/F1 + 技能级误报/漏报报表
python eval_sft.py                        # --limit 0 全量

# 6. 端到端推理：直接对原始 CSV 跑预测
python infer_csv.py                       # --n 50 / --start 100
```

## 数据集口径（重要）

- 源数据：BOSS直聘「3月新增-江苏-互联网AI」，20874 行 × 125 列
- 去重：按 **JD 正文**（去空白）去重后切分，杜绝训练/测试泄漏
- 标签：**纯词典抽取**，且只从输入可见的截断文本中抽取；平台 showSkills
  标签含大量非技能噪声（"工作简单""可带手机"），默认不并入
- 剔除无技能命中岗位后：训练 8982 条 / 测试 498 条，覆盖 208 种技能
- 统计双口径：`技能统计.xlsx` 同时含「含重复岗位」与「去重岗位(含市场占比%)」

## 底座与训练参数

| 项 | 值 |
|---|---|
| 底座 | `unsloth/Qwen3-8B-unsloth-bnb-4bit`（预量化 4bit，约 7GB） |
| 微调方式 | QLoRA（r=16, alpha=32，7 个线性层全挂） |
| `max_seq_length` | 1024 |
| batch / 梯度累积 | 1 / 8 |
| learning_rate | 2e-4，cosine |
| epochs | 1（可加大） |
| 显存优化 | adamw_8bit + `use_gradient_checkpointing="unsloth"` |
| 可训练参数 | 43.6M / 8.23B（0.53%） |
| 训练技巧 | chat template 关闭思考模式；`train_on_responses_only` 只对回复段算 loss |

OOM 时优先降 `max_seq_length` 到 512，其次减小 `gradient_accumulation_steps`。

## 实验记录

见 `Docs/训练记录.md`：v1（脏标签，已废弃）→ v2（纯词典口径）的完整过程、
指标与 6 条踩坑清单（HF 离线、hf-mirror Xet 401、Unsloth 参数名、TRL 版本兼容、
Qwen3 思考模式、欠训练复读）。

## 产物导出（待做）

LoRA adapter → 合并回底座 → 转 GGUF（Q4_K_M）→ 接入 Ollama 本地推理。
