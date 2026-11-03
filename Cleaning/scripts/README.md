# scripts/ — 清洗管线脚本

| 脚本 | 说明 |
|---|---|
| `run_extract.py` | 主脚本：CSV → 样本 txt → 云端 Qwen3-8B 逐条抽取 → 别名归一 → 黑名单过滤 → Excel/CSV |

## run_extract.py 速查

```bash
python scripts/run_extract.py                      # 全流程，默认 30 条
python scripts/run_extract.py --txt-only           # 只导样本 txt，不调 API
python scripts/run_extract.py --n 50 --input "..." # 临时换条数 / 文件
```

- **配置在脚本顶部**（API_KEY、INPUT_CSV、N），命令行参数可临时覆盖
- 自动加载 `../prompts/extract_skills.md`、`../rules/alias_map.yaml`、`../rules/blocklist.yaml`，
  改这三个文件后重跑即生效，无需改代码
- 一次一条请求、串行、失败指数退避（2s→32s 共 5 次）；结果逐条落盘，中断不丢
- 唯一第三方依赖 `openpyxl`（写 Excel），未装自动降级 CSV
- 产物在 `../out/`，文件名带时间戳，重复运行不覆盖

## 待补脚本（按链路顺序）

| 脚本 | 职责 |
|---|---|
| `normalize.py` | 大规模归一化 + pending 别名人工确认流程（当前由 run_extract 内嵌的简易版承担） |
| `evaluate.py` | 对 gold 集算 recall / precision，替代人工目测 |
| `stats.py` | 全量数据的技能频次、两类占比、交叉统计 |
