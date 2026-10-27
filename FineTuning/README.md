# FineTuning

模型微调模块。集中管理底座模型选择、数据集构建、QLoRA 训练与导出部署。

## 目录说明

| 目录 | 用途 | 是否提交 |
|---|---|---|
| `config/` | 超参配置（yaml） | 是 |
| `Datasets/Raw/` | 原始数据集 | 否，仅保留 .gitkeep |
| `Datasets/Processed/` | 清洗后的训练数据 | 否，仅保留 .gitkeep |
| `Datasets/Samples/` | 脱敏小样本（格式参考） | 是 |
| `Scripts/` | 训练、合并、导出脚本 | 是 |
| `Notebooks/` | 实验用 notebook | 是 |
| `Outputs/` | 训练产物（LoRA 权重等） | 否，仅保留 .gitkeep |
| `Docs/` | 训练记录与踩坑笔记 | 是 |

## 底座模型

- 模型：Qwen3-7B（4-bit 量化底座）
- 微调方式：QLoRA
- 运行环境：WSL2 + Ubuntu 22.04
- 硬件：RTX 5070 12GB
- 工具链：Unsloth + bitsandbytes

## 训练参数基线（适配 12GB 显存）

| 参数 | 值 |
|---|---|
| `max_seq_length` | 1024 |
| `per_device_train_batch_size` | 1 |
| `gradient_accumulation_steps` | 8 |
| `lora_rank (r)` | 16 |
| `lora_alpha` | 32 |
| `learning_rate` | 2e-4 |
| `num_train_epochs` | 3 |

若出现 OOM，优先把 `max_seq_length` 降到 512，其次减少 `gradient_accumulation_steps`。

## 产物导出

LoRA adapter → 合并回底座 → 转 GGUF（Q4_K_M）→ 接入 Ollama 本地推理。