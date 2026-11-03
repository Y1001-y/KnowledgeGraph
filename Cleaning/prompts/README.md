# prompts/ — 抽取提示词

| 文件 | 说明 |
|---|---|
| `extract_skills.md` | **当前生效的 prompt**。整个文件就是 system prompt，无任何元信息 |
| `CHANGELOG.md` | 版本演进记录（v1→v6），每版含结构、改动点、实测指标 |

## 修改规矩

1. 改前先看 CHANGELOG 最后一版，避免重复或冲突的改动
2. 一次只改一处，改完用 `eval/jd-sample-10.txt` 的 dev 集（第 1–5 条）验证
3. 改完必须在 CHANGELOG 加一行：版本号、日期、改了什么、为什么
4. 示例只能取自 dev 集，不得取自 test 集（第 6–10 条）
5. 剩余噪声交给 `../rules/blocklist.yaml`，不要无限制往 prompt 里堆禁止条目
