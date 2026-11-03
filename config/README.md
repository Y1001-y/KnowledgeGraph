# config/ — 全局配置

存放跨模块的配置文件。**只放配置，不放 prompt**（prompt 在 `Cleaning/prompts/`，因为它是
需要迭代的算法资产，不是静态参数）。

| 文件 | 说明 |
|---|---|
| `skill-config.xml` | 早期技能配置（词典路线遗留，供参考） |

清洗管线的运行参数（模型 ID、base_url、温度、并发、重试、截断长度）目前记录在
`Cleaning/config.yaml`；API 密钥走环境变量 `LLM_API_KEY` 或 `Cleaning/.env`，**任何密钥都不得放进本目录**。
