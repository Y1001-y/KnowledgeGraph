

# 数据预处理阶段
## 三个 CSV 的结构不一致
### 原因
BOSS 导出文件是 140 列 / 125 列的宽表，关键字段藏在 jobInfo_jobName、jobInfo_showSkills、jobInfo_postDescription 里
第三个文件只有 5 列中文表头
### 解决方案 
写一个 normalize() 做字段适配层，用列名特征判断格式：
```python
if "jobInfo_jobName" in cols or "jobInfo_positionName" in cols:
    out["position"]    = df["jobInfo_jobName"].fillna(df["jobInfo_positionName"])
    out["skill_tags"]  = df["jobInfo_showSkills"]      # 官方技能标签
    out["description"] = df["jobInfo_postDescription"] # 长文本描述
else:
    out["position"]    = df.get("岗位名称")
    out["skill_tags"]  = df.get("岗位技能")
    out["description"] = df.get("岗位描述")
```
统一成 position / skill_tags / description / experience / degree / salary / company / city / source_file 九个标准字段后再合并，后续逻辑不用关心来源。

## 关键词提取的误匹配（准确性问题）

### 原因
中文文本没有空格分词边界，正则匹配 C 时把“C端产品”“C++”里的字符也算进去了，导致 C 出现 50,824 次直接冲到第一，完全失真。

### 解决方案

1.设置成长词优先并且添加边界（比如 c++比c的优先级更高）
```python
_sorted = sorted(set(SKILL_KEYWORDS), key=len, reverse=True)  # 长词先匹配：C++ 优先于 C
for k in _sorted:
    pat = re.escape(k)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9+#.]{0,5}", k):        # 短英文词才加边界
        pat = r"(?<![A-Za-z0-9+#.])" + pat + r"(?![A-Za-z0-9+#.])"
```
并且(?<!...) 要求前面不是字母数字，(?!...) 要求后面不是——这样“C端”“Redis”里就不会误抓出单独的字母。

2.规范词典
拆开 "Go/Golang" 这种用斜杠拼的槽位（正则里 \ 转义后会失配），改为独立的 "Go"、"Golang"
补 "C语言"、"R语言" 这类中文写法
词典按类别分组（语言/前端/后端/数据库/大数据/AI/云原生/测试/安全）

3.双来源合并去重
```python
found = 原始技能标签.split(";")  +  正则匹配描述全文
# 归一化去重：key = s.lower().replace(" ", "")，保序
```
C出现频次明显下降 更符合实际情况 数据更有效

## openpyxl 导出报 IllegalCharacterError
### 原因
岗位描述从网页抓取，夹带了不可见控制字符（\x0c 换页符、零宽空格 \u200b、BOM 等），openpyxl 的 check_string 会直接拒绝。

### 解决方法
编写一个函数 通过定义网页常见的非法字符并且检查所有即将导出的数据 如果有出现对应字符就进行替换 保证可以正常导出 不会被拒绝 
```python
_ILLEGAL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u2028\u2029\u200b-\u200f\ufffe\uffff]")

def sanitize_for_export(df):
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_string_dtype(df[c]) or df[c].dtype == object:
            df[c] = df[c].map(lambda v: _ILLEGAL_RE.sub("", v)
                              if isinstance(v, str) and _ILLEGAL_RE.search(v) else v)
    return df

```
Excel 和 SQL 导出前都先过一遍这个函数,保证数据干净有效


