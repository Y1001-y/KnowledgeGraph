# 前置准备
```commandline
# 安装pandas
pip install pandas openpyxl -i https://mirrors.aliyun.com/pypi/simple/
```

# 使用说明
## 源数据
脚本采用的是绝对路径 源数据格式是csv 在运行之前需要把数据改成自己本地的绝对路径
### 方法
修改`DataCleaning.py`中的第20行到第26行 根据文件情况修改成自己的目录
```python
# ============ 1. 配置区 ============
INPUT_DIR = r"D:\study\KnowledgeGraph\Origin data"   # 自动扫描该目录下所有 csv/xlsx（可改成其他目录）
INPUT_FILES = [  # 手动指定输入文件（支持绝对/相对路径）；设为 None 则自动扫描 INPUT_DIR
    r"D:\study\KnowledgeGraph\Origin data\5月-1月-江苏-互联网AI.csv",
    r"D:\study\KnowledgeGraph\Origin data\3月新增-江苏-互联网AI.csv",
    r"D:\study\KnowledgeGraph\Origin data\3月-江苏-互联网AI-本科 (1).csv",
]
```
## 运行 
先运行`DataCleaning.py` 导出的数据有两份 一份是SQL格式 一份是Excel 此处注意 数据去重 SQL不能直接使用
**导出的文件都是在当前目录中 和这两个文件平级**
再运行`ExportSQL.py` 他会自动读取刚才导出的Excel 并且进行去重 然后导出成SQL


# 实现逻辑说明

本部分说明两个脚本的内部实现逻辑：

| 脚本           | 输入                     | 输出                              |
| ------------ | ---------------------- | ------------------------------- |
| `数据清洗脚本.py`  | 原始 CSV / Excel（招聘网站导出） | `清洗结果.xlsx`、`清洗结果.sql`          |
| `数据库转换脚本.py` | `清洗结果.xlsx`            | `技能岗位数据库.db` / `.sql` / `.xlsx` |
运行顺序必须是先清洗、后建库（第二个脚本依赖第一个的输出文件）。

---

## 一、`DataCleaning.py` 实现逻辑

整体流程：读文件 → 适配字段 → 清洗文本 → 提取技能 → 去重 → 导出

```
原始 CSV/Excel
   │
   ├─ collect_input_files()   确定要读哪些文件
   ├─ load_one()              多编码尝试读取
   ├─ normalize()             不同 schema 统一成 9 个标准字段
   ├─ clean_data()            ｜ clean_text()       文本清洗
   │                          ｜ extract_skills()   技能提取
   │                          ｜ dropna/drop_duplicates 去空去重
   └─ export_excel() / export_sql()   （导出前 sanitize_for_export）
```

### 1. 配置区

脚本顶部集中放可调参数，改数据源不用动业务代码：

```python
INPUT_FILES  # 显式指定输入文件列表（推荐）；设为 None 则自动扫描 INPUT_DIR
OUTPUT_EXCEL / OUTPUT_SQL / TABLE_NAME
SKILL_KEYWORDS  # 技术关键词词典（约 400 项）
```

### 2. 输入文件收集 `collect_input_files()`

- 优先使用 `INPUT_FILES` 白名单，避免把下载目录里无关的表格一起读进来
- 若为 `None`，则用 `glob` 扫描 `*.csv/*.xlsx/*.xls`，并排除自身输出文件和 Excel 临时文件（`~$` 开头）

### 3. 文件读取 `load_one()`

- 按扩展名分流：`.xlsx/.xls` → `pd.read_excel`，其余 → `pd.read_csv`
- CSV 编码**逐个兜底尝试** `utf-8-sig → utf-8 → gbk → gb18030`，解决招聘网站导出文件的 BOM 和 GBK 混杂问题
- 每个文件都用 `try/except` 包裹，单文件失败只打印告警，不中断整批任务

### 4. 字段适配 `normalize()`

思路：先统一 schema，再走清洗逻辑，让下游完全不关心数据来源。

用列名特征判断格式：

| 判断条件                                         | 格式                   | 岗位字段                                          | 技能标签                       | 描述                        |
| -------------------------------------------- | -------------------- | --------------------------------------------- | -------------------------- | ------------------------- |
| 含 `jobInfo_jobName` 或 `jobInfo_positionName` | BOSS 直聘宽表（125~140 列） | `jobInfo_jobName`，空值回退 `jobInfo_positionName` | `jobInfo_showSkills`（分号分隔） | `jobInfo_postDescription` |
| 其他                                           | 简洁表（5 列中文表头）         | `岗位名称`                                        | `岗位技能`                     | `岗位描述`                    |

统一输出 9 个字段：

```
position, skill_tags, description, experience, degree, salary, company, city, source_file
```

`source_file` 记录数据来源文件名，便于后续追溯和分层统计。

### 5. 文本清洗 `clean_text()`

对每个文本单元格依次：

1. 空值直接返回 `pd.NA`
2. 删除 ASCII 控制字符 `[\x00-\x08\x0b\x0c\x0e-\x1f]`（网页抓取带入的换页符等）
3. `\s+ → 单个空格`，再 `strip()` 去首尾空白
4. 低价值占位值（`""`、`nan`、`none`、`null`、`-`、`--`、`无`、`不限`）统一转为 `pd.NA`

### 6. 技能提取 `extract_skills()`

一个岗位的技能来自两个来源，合并去重后作为该岗位的标签集合：

来源 ①：原始技能标签

- 按 `; ； , ， 、 / |` 多种分隔符拆分（招聘网站的标签分隔符不统一）
- 逐项 `strip` 并过滤无效值

来源 ②：岗位描述全文词典匹配

```python
SKILL_RE = re.compile("|".join(_parts), re.IGNORECASE)
```

构建正则时做了两处关键处理：

- 长词优先：词典按长度降序排列，保证 `C++` 先于 `C` 被匹配到
- 短英文词加词边界：对 `C`、`R`、`Go`、`Java` 这类短词包上前后断言
  ```python
  (?<![A-Za-z0-9+#.])  C  (?![A-Za-z0-9+#.])
  ```
  否则中文文本里“C端产品”“C语言”会把 C 全抓出来——实测不做处理时 C 出现 50,824 次直接冲到榜首，加边界后降为 10,774 次，排序恢复正常。

合并去重

- 大小写不敏感归一化：`key = s.lower().replace(" ", "")`
- 用 `dict` 保序去重，输出 `"Java, Spring, MySQL"` 形式的逗号分隔字符串
- 词典命中时回填**词典标准写法**（如文本里写 `python` 也统一成 `Python`），保证后续聚合不出分裂

### 7. 行级清洗与去重 `clean_data()`

```
① 岗位、技能分别做 clean_text / extract_skills
② 补充字段（经验、学历、薪资、公司、城市）统一清洗
③ 岗位与技术全为空的行删除（how="all"，只要有一个有效就保留）
④ 空值兜底填 "未注明岗位" / "未注明技术"
⑤ 按 (position, skill, company) 三元组去重，保留首条
⑥ reset_index
```

用三元组而非 `position + skill` 去重，是为了保留"同一公司同一岗位的不同薪资档位"这类有效记录。

### 8. 导出 `export_excel()` / `export_sql()`

**导出前统一兜底 `sanitize_for_export()`**

```python
_ILLEGAL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u2028\u2029\u200b-\u200f\ufffe\uffff]")
```

清掉 openpyxl 拒绝写入的不可见字符（控制字符、零宽字符、BOM 等），否则整个导出会抛 `IllegalCharacterError` 中断。

> 注意：列类型判断必须用 `pd.api.types.is_string_dtype()`，pandas 3.0 起字符串列 dtype 是 `str` 而非 `object`，只用 `dtype == object` 会导致清洗不生效。

**Excel 输出（两个 sheet）**

- `岗位技术明细`：全部清洗后记录
- `技能词频统计`：把 `skill` 列按 `, ` 拆开后计数，倒序排列

**SQL 输出**

- 根据 `df.columns` 动态生成 `CREATE TABLE`，类型推断规则：`int → INTEGER`、`float → REAL`、其余 → `TEXT`
- 逐行生成 `INSERT`：空值写 `NULL`、数字直接写、字符串**转义单引号**（`'` → `''`）防语法错误
- 文件头带 `DROP TABLE IF EXISTS`，可重复导入

---

## 二、`ExportSQL.py` 

把"一行一个岗位、技能挤在逗号串里"的宽表，拆成**技能 ↔ 岗位 多对多**的关系模型。

```
清洗结果.xlsx
   │
   ├─ build_tables()     一次遍历同时累积：技能频次、技能→岗位集合、岗位计数
   │     ├─ skill          技能表（去重后的技能 + 频次 + 关联岗位数）
   │     ├─ position       岗位表（去重后的岗位 + 招聘条数）
   │     ├─ skill_position 关联表（多对多，去重）
   │     └─ raw_tags       岗位原始技能标签（回溯用）
   └─ export_sql() / export_sqlite() / export_excel()
```

### 1. 读取

从 `清洗结果.xlsx` 的 `岗位技术明细` sheet 读入（143,793 行）。文件不存在时直接提示先跑第一个脚本。

### 2. 关系构建 `build_tables()`

**核心数据结构（一次遍历，同时给三个累加器）**

```python
skill_counter    = {}   # 技能名 -> 出现频次
skill_positions  = {}   # 技能名 -> {岗位名, ...}   ← 用集合天然去重
position_names   = {}   # 岗位名 -> 招聘条数
```

**遍历时对每行**：

1. 取 `position`，跳过空值和无效值（含"未注明岗位"），超长岗位名截断到 100 字
2. `position_names[pos] += 1`
3. 把 `skill` 字符串按 `, ` 拆开，对每个有效技能：
   - `skill_counter[s] += 1`
   - `skill_positions[s].add(pos)`

**去重逻辑体现在哪**

- 技能去重：`skill_counter` 的 key 天然唯一
- 岗位去重：`position_names` 的 key 天然唯一
- 关系去重：`skill_positions` 的值是 `set`，同一岗位重复出现只算一次
- 最后 `relation.drop_duplicates()` 再做一次保险

**ID 分配**：按频次倒序编号，高频技能 ID 靠前，便于肉眼检查。

```python
skills.insert(0, "skill_id", range(1, len(skills) + 1))
positions.insert(0, "position_id", range(1, len(positions) + 1))
```

**关联映射必须用 dict**

```python
skill_id_map = dict(zip(skills["skill_name"], skills["skill_id"]))
pos_id       = dict(zip(positions["position_name"], positions["position_id"]))
rel = [(pos_id[p], skill_id_map[s]) for s, plist in skill_positions.items() for p in plist]
```

不要用 `skills.loc[skills["skill_name"] == s, "skill_id"].iloc[0]`——那是每行全表扫描，34,594 技能 × 50 万关联会跑到 10 分钟以上；字典映射后整个脚本 47 秒完成。

### 3. 表结构设计

**`skill` 技能表**

| 字段               | 说明                               |
| ---------------- | -------------------------------- |
| `skill_id`       | 主键，按频次倒序编号                       |
| `skill_name`     | 技能名（来自清洗阶段的标准化写法）                |
| `frequency`      | 频次 = 需要该技能的岗位条数                  |
| `position_count` | 关联的不同岗位数（如 Java 对应 10,460 个岗位标签） |

**`position` 岗位表**

| 字段              | 说明                |
| --------------- | ----------------- |
| `position_id`   | 主键                |
| `position_name` | 岗位名               |
| `job_count`     | 该岗位名在原始数据中出现的招聘条数 |

**`skill_position` 关联表**

| 字段            | 说明                     |
| ------------- | ---------------------- |
| `position_id` | 联合主键 + 外键 → `position` |
| `skill_id`    | 联合主键 + 外键 → `skill`    |

联合主键 `(position_id, skill_id)` 从数据库层面保证关系不重复；两个外键保证不会出现孤儿关联（脚本已校验孤儿数 = 0）。

### 4. 三种导出

**`export_sql()`** — MySQL 风格

- `DROP TABLE IF EXISTS` 按依赖反序（先删关联表）
- 建表带主键、外键约束
- 字符串统一 `q()` 转义单引号
- 插序：先 `position`、再 `skill`、最后 `skill_position`（满足外键约束）

**`export_sqlite()`** — 可直连的数据库文件

- `to_sql(..., if_exists="replace")` 三张表
- 额外建两个索引加速双向查询：
  ```sql
  CREATE INDEX idx_sp_skill    ON skill_position(skill_id);
  CREATE INDEX idx_sp_position ON skill_position(position_id);
  ```

**`export_excel()`** — 便于人工查看，四个 sheet

| sheet       | 内容                                                        |
| ----------- | --------------------------------------------------------- |
| 技能表         | 原始三列                                                      |
| 岗位表         | 原始三列                                                      |
| 技能-岗位关联(可读) | 关联表 join 出 `skill_name + position_name + frequency`，按频次倒序 |
| 岗位原始技能标签    | 岗位名 + 原始标签串，用于回溯核对                                        |

### 5. 实际数据规模

```
skill            34,594 条
position         56,755 条
skill_position  508,536 条
孤儿关联                 0
```

---

## 三、两个脚本的分工边界

| 关注点    | 数据清洗脚本              | 数据库转换脚本                |
| ------ | ------------------- | ---------------------- |
| 数据来源识别 | ✅ 多格式适配             | ❌ 只认清洗结果               |
| 文本清洗   | ✅                   | ❌                      |
| 技能抽取   | ✅ 词典 + 词边界          | ❌                      |
| 频次统计   | ✅ 简单词频（Excel sheet） | ✅ 技能频次 + 岗位数           |
| 关系建模   | ❌ 保持宽表              | ✅ 多对多三表                |
| 去重口径   | 按 (岗位, 技能, 公司) 去记录  | 按技能名 / 岗位名 / 关系三元组分别去重 |

换数据源时只改第一个脚本的 `normalize()`；换数据库（MySQL / PostgreSQL / 数仓）时只改第二个脚本的 `export_*()`。
