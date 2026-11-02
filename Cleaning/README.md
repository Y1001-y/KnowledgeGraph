# Cleaning — 数据清洗管线（当前路线）

从 BOSS 直聘 JD 到「技能频次 + 两类占比」的完整链路资产。**当前唯一在跑的清洗方案**，
取代了归档里的两条旧路线（`../归档/DataPreprocessing/` 词典脚本、
`../归档/ModelFineTuning/` 本地微调）。

```
Origin data/*.csv
   │
   ├─ ① 抽取   云端 Qwen3-8B + prompts/extract_skills.md      → out/skills.jsonl
   ├─ ② 归一   rules/alias_map.yaml（确定性，可审计）
   ├─ ③ 分类   rules 命中即定类；长尾交 chinese-roberta（待训）
   └─ ④ 统计   频次 / 两类占比 / 按岗位·学历·经验交叉
```

分工原则：**读懂文本交给生成式模型，保持口径交给确定性代码。**
抽取允许有噪声（后面能过滤），归一与分类必须零随机（否则频次不可比）。

## 目录说明

| 路径 | 内容 | 说明 |
|---|---|---|
| `prompts/extract_skills.md` | 当前生效的抽取 prompt（v3） | **纯 prompt 文本，整个文件就是 system prompt**，可直接全选复制，没有任何元信息、front matter 或注释 |
| `prompts/CHANGELOG.md` | 版本演进与每轮实测结论 | 改 prompt 必须同步写一条，记录改了什么、为什么、指标怎么变 |
| `config.yaml` | 模型 ID、接口地址、温度、并发、重试、截断长度 | 只放参数，不放密钥；密钥走环境变量 / `.env` |
| `eval/jd-sample-10.txt` | 10 条样本，`job_id` 为 `3yxz-000` ~ `3yxz-009` | **第 1–5 条 = dev**（调 prompt 用，prompt 里的示例取自这里）；**第 6–10 条 = test**（只在验收时跑一次） |
| `eval/results/` | 每轮跑批的结果快照 | 命名 `YYYYMMDD-runN.jsonl`，一行一条 `{"job_id","skills"}` |
| `rules/alias_map.yaml` | 别名归并表（JS → JavaScript、k8s → Kubernetes） | 归一化用，确定性；新增映射需人工确认 |
| `rules/blocklist.yaml` | 后处理黑名单（领域词、指标词、平台标签噪声） | 区分 `drop` 与 `flag` 两级处理 |
| `scripts/` | 抽取 / 归一 / 统计脚本（待补） | 骨架可参考 `../FineTuning/Scripts/infer_csv.py` |
| `out/` | 运行产物（`skills.jsonl`、`failed.jsonl`） | 已进 `.gitignore`，不入库 |

## 当前 prompt 状态（v3）

- 结构：7 条禁止 + 8 条规则 + 5 个示例 + 输出格式
- 已解决：「车辆 / 行人 / 道路 / 障碍物」这类**被操作对象**不再被抽出（靠示例 2 压住，纯规则压不住）
- **未解决**：`自动驾驶`、`机器人导航`（领域名）、`标注准确率`、`质量标准`（考核指标）仍会漏进来
- 判断：8B 的指令跟随容量已接近上限，继续加规则边际收益递减，**剩余噪声交给 `rules/blocklist.yaml` 过滤**，不再指望 prompt 100% 干净

上一轮实测（`eval/results/20261102-run1.jsonl`，第 1 条 `3yxz-000`）：
严格口径 recall 9/9 = 100%，precision 9/21 = 42.9%，其中 8 个是黑名单能稳定过滤的词。

## 使用流程

**调 prompt（dev）**

1. 打开 `prompts/extract_skills.md`，整份复制到平台的 **System Prompt** 输入框（不是对话区）
2. 参数：`temperature=0`、`top_p=1`、`max_tokens=512`、思考模式关闭
3. 从 `eval/jd-sample-10.txt` 取第 1–5 条，**新开会话**逐条粘（一次一条，不要连贴）
4. 对着 JD 原文核「多抽了什么、漏了什么」，改 prompt → 重测 → 在 `CHANGELOG.md` 记一笔

**验收（test）**

第 6–10 条在 prompt 定稿前**不要碰**。定稿后跑一次，结果存
`eval/results/YYYYMMDD-final.jsonl`，这一批的 recall / precision 才是能写进报告的指标。
（dev 集里 3 条被 prompt 示例覆盖过，跑出的分数不作为效果证据。）

**跑批**

按 `config.yaml` 的并发与重试策略逐条调用，结果 append 到 `out/skills.jsonl`，
失败单条进 `out/failed.jsonl` 便于只重跑失败子集。14 万条量级见
`../归档/README.md` 第一节的成本对比表。

## 目录边界（避免重复放置）

| 内容 | 应该放哪 | 不要放哪 |
|---|---|---|
| prompt、评估集、归一规则、黑名单、抽取产物 | 本目录 | `config/`（只放系统级配置）、`FineTuning/`（已归档路线） |
| 原始 CSV | `../Origin data/` | 本目录（只读引用，不复制） |
| 训练集 / 测试集 / 历史技能统计 | `../FineTuning/Datasets/` | 本目录（那是路线二的产物，保留归档即可） |
| 分类器代码与权重 | 待定（预计 `classifier/`） | 本目录（本目录只负责清洗与统计） |
