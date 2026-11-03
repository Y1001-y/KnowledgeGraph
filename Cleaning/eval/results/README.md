# results/ — 各轮批量抽取结果快照

## 命名规范

```
YYYYMMDD-runN.jsonl     人工抽测轮（Playground / 小批量）
skills_<时间戳>.jsonl   run_extract.py 自动产出（out/ 中审核后归档至此）
```

每行一条 JSON：`{"job_id", "skills", "dropped", "flagged", "status"}`。

## 现有文件

| 文件 | 说明 |
|---|---|
| `20261102-run1.jsonl` | 早期提示词对 10 条样本的抽取结果，**精度基线**（recall 9/9，precision 9/21），自原 `FineTuning/Outputs/prompt/20261102/001.txt` 重命名而来 |
| `skills_20261103_093506.jsonl` | 首次 30 条全量试跑（后处理集成前），暴露福利词、泛词、协作对象三类误抽模式 |
| `skills_20261103_094908.jsonl` | 过滤词表首次集成后的 30 条结果 |
| `skills_20261103_100324.jsonl` | 别名归一化集成后的 30 条结果，人工复检结论促成后续过滤词表扩充 |

## 用途

- 对比不同修订轮次提示词 / 过滤规则的指标变化（配合 `../gold/` 计算）
- 追溯某个词条被抽取或被过滤的原因
- 仅归档具有对比价值的结果，中间失败运行不必保留
