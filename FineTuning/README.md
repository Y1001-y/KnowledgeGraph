# FineTuning

> **当前状态：微调路线已搁置（2026-11-02）。**  
> 本目录不再包含模型权重、训练脚本和评估产物。现在它承担两个职责：  
> ① 保存已产出的训练集 / 测试集 / 技能统计；② 保存数据准备与数据体检脚本，  
> 供当前「云端抽取 → 本地归一化 → 本地分类 → 统计」链路复用。
>
> 历史方案（Unsloth + QLoRA 微调 Qwen3-8B）停止的技术原因见  
> [`归档/ModelFineTuning/`](../归档/ModelFineTuning/README.md) 第二节；
> 三条路线的横向对比与最终选型依据见 [`归档/README.md`](../归档/README.md) 第一、二节。

## 一、当前数据链路

```
Origin data/*.csv（BOSS 直聘导出）
  │
  ├─ ① 云端抽取      Qwen3-8B（硅基流动 / 阿里云百炼）+ ../Cleaning/prompts/extract_skills.md
  │                  一条 JD 一次请求，结果落 ../Cleaning/out/skills.jsonl
  │
  ├─ ② 本地归一化    别名映射表：../Cleaning/rules/alias_map.yaml
  │                  映射表来源：Scripts/prepare_dataset.py 内置的 209 条技能词典
  │
  ├─ ③ 本地分类      chinese-roberta-wwm-ext（102M），hard / soft 二分类
  │                  词典已覆盖的直接定类，长尾才走模型，结果回写映射表
  │
  └─ ④ 统计          技能频次、两类占比、按岗位 / 学历 / 经验交叉
```

云端只负责「读出 JD 里写了哪些技能」，不做归一化、不做分类。归一化和分类都是本地  
确定性环节，保证同一技能永远落在同一类，频次统计才有意义。

## 二、目录说明

| 目录                                 | 当前内容                                                | 说明                                    |
| ---------------------------------- | --------------------------------------------------- | ------------------------------------- |
| `Datasets/Raw/`                    | 空（`.gitkeep`）                                       | 原始数据放 `../../Origin data/`，这里不入库      |
| `Datasets/Processed/`              | 训练集 66M + 14M jsonl、测试集 3.7M、`技能统计.xlsx/csv`        | **保留**。数据本身与模型无关，后续归一化、分类训练、统计都要用     |
| `Datasets/Samples/`                | 空（`.gitkeep`）                                       | 10 条样本已迁至 [`../Cleaning/eval/jd-sample-10.txt`](../Cleaning/eval/jd-sample-10.txt)（评估资产归清洗管线） |
| `Scripts/`                         | `prepare_dataset.py`、`audit_data.py`、`infer_csv.py` | **保留**，见下节用途                          |
| `Outputs/eval/`、`Outputs/predict/` | 空（`.gitkeep`）                                       | 原是微调模型的评估与预测产物，模型废弃后一并清空              |
| `Docs/`                            | `训练记录.md`                                           | 历史踩坑笔记，其中 Qwen3 思考模式等条目对云端调用仍然适用      |
| `Notebooks/`                       | 空（`.gitkeep`）                                       | —                                     |
| `config/`                          | 空                                                   | 超参 yaml 属微调时代产物，已随训练脚本移除              |

## 三、保留下来的脚本还能干什么

| 脚本                   | 原用途                           | 现在怎么用                                                    |
| -------------------- | ----------------------------- | -------------------------------------------------------- |
| `prepare_dataset.py` | 正则词典抽技能 → 生成 SFT jsonl        | **只用它的词典部分**（209 条规范名 + 别名），搬迁出来做归一化映射表；SFT 生成部分已无用      |
| `audit_data.py`      | 数据体检 8 个维度（空值、重复、长度分布、技能覆盖率等） | 原样可用，清洗前后各跑一次，衡量清洗质量                                     |
| `infer_csv.py`       | 调本地微调模型批量推理                   | 骨架可直接复用：读 CSV → 批量调用 → 写回结果。把推理后端从本地模型换成云端 API 就是现在的抽取脚本 |

## 四、已移除的内容

| 移除项                                                                                            | 体积   | 时间         |
| ---------------------------------------------------------------------------------------------- | ---- | ---------- |
| `Outputs/qwen3-8b-skills-lora/`（LoRA adapter ×3 + optimizer.pt ×2 + tokenizer / trainer_state） | 454M | 2026-11-02 |
| `Scripts/unsloth_compiled_cache/`                                                              | 2.6M | 2026-11-02 |
| `Scripts/train_sft.py`、`eval_sft.py`、`test_load.py`、`download_model.sh`                        | —    | 2026-11-02 |
| `Outputs/eval/`（summary.json、技能级报表.xlsx、样本级明细.xlsx）                                            | 53K  | 2026-11-02 |
| `Outputs/predict/`（两轮预测结果 csv / xlsx）                                                          | 36K  | 2026-11-02 |

整个目录从 541M 降到 85M，剩下的 85M 全是数据集。

## 五、下一步

> 清理链路的资产已独立到 [`../Cleaning/`](../Cleaning/)，以下步骤在那边执行。

1. 定稿 [`../Cleaning/prompts/extract_skills.md`](../Cleaning/prompts/extract_skills.md)，用
   [`../Cleaning/eval/jd-sample-10.txt`](../Cleaning/eval/jd-sample-10.txt) 的 6–10 条
   （未被示例覆盖的部分）算第一版 recall / precision
2. 搭云端批量抽取脚本（基于 `infer_csv.py` 骨架）：按 JD 正文去重、并发 3、指数退避、  
   断点续跑，结果写 `../Cleaning/out/skills.jsonl`
3. 从 209 条词典生成 `../Cleaning/rules/alias_map.yaml`，归一化后用
   `../Cleaning/rules/blocklist.yaml` 过滤领域词与指标词
4. 抽 2000 条训练分类器，用 macro-F1 和 soft 类 recall 评估，不看 accuracy
5. 全量跑批 → 统计 → 出图

详见 [`归档/ModelFineTuning/README.md`](../归档/ModelFineTuning/README.md) 第二节「停止的技术原因」，  
那里有输出上界锁死的机理推导与吞吐实测数据。
