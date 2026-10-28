# -*- coding: utf-8 -*-
"""
就业数据清洗脚本（BOSS直聘岗位数据）
功能：
  1. 读取多个 CSV/Excel 文件，自动兼容两种格式：
     - BOSS直聘格式（jobInfo_jobName / jobInfo_positionName / jobInfo_showSkills / jobInfo_postDescription ...）
     - 简洁格式（岗位名称 / 岗位技能 / 经验 / 学历 / 岗位描述）
  2. 提取两个核心字段：岗位（position）、技术（skill，含原始技能标签 + 从描述中提取的技术关键词）
  3. 技能提取：内置 IT 技术关键词词典（最长优先匹配），对岗位描述全文扫描，去重、归一化
  4. 导出 Excel（清洗结果.xlsx，含"岗位技术明细"与"技能词频统计"两个 sheet）和 SQL（清洗结果.sql）
依赖：pip install pandas openpyxl
作者：ima
"""

import os
import re
import glob
import pandas as pd

# ============ 1. 配置区 ============
INPUT_DIR = r"D:\study\KnowledgeGraph\Origin data"   # 自动扫描该目录下所有 csv/xlsx（可改成其他目录）
INPUT_FILES = [  # 手动指定输入文件（支持绝对/相对路径）；设为 None 则自动扫描 INPUT_DIR
    r"D:\study\KnowledgeGraph\Origin data\5月-1月-江苏-互联网AI.csv",
    r"D:\study\KnowledgeGraph\Origin data\3月新增-江苏-互联网AI.csv",
    r"D:\study\KnowledgeGraph\Origin data\3月-江苏-互联网AI-本科 (1).csv",
]
OUTPUT_EXCEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "清洗结果.xlsx")
OUTPUT_SQL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "清洗结果.sql")
TABLE_NAME = "job_info"

# ============ 2. IT 技术关键词词典（用于从岗位描述中精准提取）============
# 长词在前优先匹配，避免 "C++" 被 "C" 抢走
SKILL_KEYWORDS = [
    # 编程语言
    "ABAP", "ActionScript", "Assembly", "Bash", "C#", "C/C++", "C++", "Clojure", "COBOL",
    "Dart", "Delphi", "Elixir", "Erlang", "F#", "Fortran", "Go", "Golang", "Groovy",
    "Haskell", "Java", "JavaScript", "Julia", "Kotlin", "Lua", "Matlab", "Objective-C",
    "OCaml", "Perl", "PHP", "PowerShell", "Python", "R语言", "Ruby", "Rust", "Scala",
    "Shell", "Solidity", "SQL", "Swift", "TypeScript", "VBA", "VB.NET", "Verilog", "VHDL",
    "C语言", "R",
    # 前端
    "React", "Vue", "Angular", "Next.js", "Nuxt", "uni-app", "Taro", "Electron",
    "HTML", "CSS", "Sass", "Less", "Webpack", "Vite", "Babel", "jQuery", "Bootstrap",
    "ElementUI", "Ant Design", "ECharts", "Three.js", "D3.js", "微信小程序", "小程序开发",
    "H5开发", "前端工程化", "Flutter", "React Native", "鸿蒙开发", "HarmonyOS",
    # 后端 / 框架
    "Spring", "SpringBoot", "Spring Cloud", "MyBatis", "Hibernate", "Netty", "Dubbo",
    "Django", "Flask", "FastAPI", "Tornado", "Scrapy", "Celery", "Laravel", "ThinkPHP",
    "Express", "Koa", "Node.js", "NestJS", ".NET", "ASP.NET", "Ruby on Rails",
    "Beego", "Gin", "grpc", "gRPC", "RESTful", "WebSocket", "微服务", "分布式",
    "高并发", "多线程", "消息队列", "中间件",
    # 数据库 / 存储
    "MySQL", "PostgreSQL", "Oracle", "SQL Server", "SQLServer", "MongoDB", "Redis",
    "Elasticsearch", "ES查询", "Memcached", "ClickHouse", "HBase", "Cassandra",
    "Neo4j", "InfluxDB", "TDengine", "OceanBase", "TiDB", "达梦数据库", "人大金仓",
    "SQLite", "Hive", "HDFS", "Hadoop", "HBase", "Hudi", "Iceberg", "Doris",
    "StarRocks", "Greenplum", "数据仓库", "数据湖", "数仓建模",
    # 大数据 / 数据分析
    "Spark", "Flink", "Kafka", "RabbitMQ", "RocketMQ", "ActiveMQ", "Pulsar",
    "Storm", "Beam", "Airflow", "DolphinScheduler", "DataX", "Kettle", "Sqoop",
    "MaxCompute", "ODPS", "实时计算", "离线数仓", "ETL", "数据治理", "数据中台",
    "数据挖掘", "数据分析", "数据建模", "用户画像", "埋点", "AB测试", "A/B测试",
    "Hologres", "Quick BI", "Tableau", "Power BI", "PowerBI", "FineBI", "FineReport",
    "Superset", "Metabase", "帆软", "Excel", "SPSS", "SAS", "Stata", "统计建模",
    "NumPy", "Pandas", "Matplotlib", "Seaborn", "SciPy", "Statsmodels",
    # AI / 机器学习
    "机器学习", "深度学习", "强化学习", "联邦学习", "迁移学习", "图神经网络", "GNN",
    "自然语言处理", "NLP", "计算机视觉", "CV算法", "OCR", "语音识别", "ASR",
    "语音合成", "TTS", "推荐系统", "搜索算法", "知识图谱", "多模态", "具身智能",
    "大模型", "LLM", "AIGC", "GPT", "BERT", "Transformer", "扩散模型", "Diffusion",
    "Stable Diffusion", "Prompt工程", "RAG", "检索增强", "LangChain", "Agent开发",
    "智能体", "模型训练", "模型部署", "模型压缩", "模型量化", "推理优化", "SFT",
    "RLHF", "LoRA", "微调", "TensorFlow", "PyTorch", "PaddlePaddle", "飞桨",
    "MindSpore", "Keras", "ONNX", "TensorRT", "OpenCV", "MMEngine", "Hugging Face",
    "Transformers", "CUDA", "CUDNN", "GPU加速", "VLLM", "vLLM", "AI工程化",
    # 云原生 / 运维 / 测试
    "Docker", "Kubernetes", "K8s", "Helm", "Istio", "Terraform", "Ansible",
    "Jenkins", "GitLab CI", "GitHub Actions", "CI/CD", "DevOps", "SRE", "AIOps",
    "Prometheus", "Grafana", "Zabbix", "ELK", "Linux", "Unix", "Windows开发",
    "Nginx", "Tomcat", "Apache", "HAProxy", "LVS", "Keepalived", "OpenStack",
    "阿里云", "腾讯云", "华为云", "AWS", "Azure", "云原生", "Serverless", "虚拟化",
    "自动化测试", "性能测试", "接口测试", "JUnit", "Pytest", "Selenium", "Appium",
    "Postman", "JMeter", "LoadRunner", "TestNG", "Cypress", "Fiddler", "Charles",
    # 安全 / 其他
    "网络安全", "渗透测试", "安全审计", "漏洞挖掘", "等保", "密码学", "安全加固",
    "Burp Suite", "Wireshark", "Nmap", "Metasploit", "防火墙", "入侵检测",
    "Git", "SVN", "Jira", "Confluence", "敏捷开发", "Scrum", "需求分析",
    "产品经理", "项目管理", "UML", "Axure", "Visio", "Figma", "Sketch",
    "MySQL调优", "SQL优化", "JVM调优", "JVM", "并发编程", "TCP/IP", "HTTP", "HTTPS",
]

# 把词典编译成正则（转义特殊字符、按长度降序；短英文词加词边界，避免 "C端" 误匹配 "C"）
_sorted = sorted({k for k in SKILL_KEYWORDS}, key=len, reverse=True)
_parts = []
for k in _sorted:
    pat = re.escape(k).replace(r"\#", "#").replace(r"\+", "+").replace(r"\.", ".")
    # 纯短英文词（如 C、R、Go、Java）要求前后不是字母数字，避免 "C端"、"Redis" 里误匹配
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9+#.]{0,5}", k) and not k.endswith("语言"):
        pat = r"(?<![A-Za-z0-9+#.])" + pat + r"(?![A-Za-z0-9+#.])"
    _parts.append(pat)
SKILL_RE = re.compile("(" + "|".join(_parts) + ")", re.IGNORECASE)

# ============ 3. 读取原始数据 ============
def load_one(path):
    """读取单个文件，自动尝试多种编码"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"无法识别文件编码: {path}")

def collect_input_files():
    if INPUT_FILES:
        return [f if os.path.isabs(f) else os.path.join(INPUT_DIR, f) for f in INPUT_FILES]
    files = []
    for pat in ("*.csv", "*.xlsx", "*.xls"):
        files += glob.glob(os.path.join(INPUT_DIR, pat))
    # 排除输出文件自身
    return [f for f in files
            if os.path.basename(f) not in (os.path.basename(OUTPUT_EXCEL),)
            and not os.path.basename(f).startswith("~$")]

# ============ 4. 格式适配：把不同 schema 映射到统一字段 ============
def normalize(df, source_file):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    cols = set(df.columns)

    if "jobInfo_jobName" in cols or "jobInfo_positionName" in cols:
        # ---- BOSS直聘格式 ----
        out = pd.DataFrame()
        out["position"] = df.get("jobInfo_jobName")
        alt = df.get("jobInfo_positionName")
        out["position"] = out["position"].fillna(alt)
        out["skill_tags"] = df.get("jobInfo_showSkills")          # 官方技能标签，分号分隔
        out["description"] = df.get("jobInfo_postDescription")
        out["experience"] = df.get("jobInfo_experienceName")
        out["degree"] = df.get("jobInfo_degreeName")
        out["salary"] = df.get("jobInfo_salaryDesc")
        out["company"] = df.get("brandComInfo_brandName")
        out["city"] = df.get("jobInfo_locationName")
    else:
        # ---- 简洁格式（岗位名称/岗位技能/岗位描述）----
        out = pd.DataFrame()
        out["position"] = df.get("岗位名称", df.get("岗位", df.get("职位")))
        out["skill_tags"] = df.get("岗位技能", df.get("技能", df.get("技术")))
        out["description"] = df.get("岗位描述", df.get("职责描述", df.get("职位描述")))
        out["experience"] = df.get("经验")
        out["degree"] = df.get("学历")
        out["salary"] = df.get("薪资")
        out["company"] = df.get("公司")
        out["city"] = df.get("城市")
    out["source_file"] = os.path.basename(source_file)
    return out

# ============ 5. 清洗函数 ============
INVALID = {"", "nan", "none", "null", "-", "--", "无", "不限"}

def clean_text(v):
    if pd.isna(v):
        return pd.NA
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(v))  # 去除 Excel 非法控制字符
    s = re.sub(r"\s+", " ", s).strip()
    return s if s.lower() not in INVALID else pd.NA

def extract_skills(skill_tags, description):
    """合并 原始技能标签 + 从描述中词典匹配到的技术关键词，去重保序"""
    found = []
    # 1) 原始技能标签（分号/逗号/顿号分隔），先做精确匹配词典归一化
    if pd.notna(skill_tags):
        parts = re.split(r"[;；,，、/|]+", str(skill_tags))
        for p in parts:
            p = p.strip()
            if not p or p.lower() in INVALID:
                continue
            found.append(p)
    # 2) 从岗位描述全文做词典匹配（忽略大小写，保留词典标准写法）
    if pd.notna(description):
        text = str(description)
        for m in SKILL_RE.finditer(text):
            word = m.group(0)
            # 找到词典中的标准写法
            std = next((k for k in _sorted if k.lower() == word.lower()), word)
            found.append(std)
    # 3) 归一化去重（大小写不敏感，保序）
    seen, result = set(), []
    for s in found:
        s = s.strip()
        key = s.lower().replace(" ", "")
        if key and key not in seen:
            seen.add(key)
            result.append(s)
    return ", ".join(result) if result else pd.NA

def clean_data(df):
    df = df.copy()
    # 岗位清洗
    df["position"] = df["position"].apply(clean_text)
    # 技能清洗 + 提取
    df["skill"] = df.apply(
        lambda r: extract_skills(r.get("skill_tags"), r.get("description")), axis=1)
    # 保留辅助字段
    for c in ("experience", "degree", "salary", "company", "city"):
        if c in df.columns:
            df[c] = df[c].apply(clean_text)
    # 删除岗位与技术均为空的行
    df = df.dropna(subset=["position", "skill"], how="all")
    df["position"] = df["position"].fillna("未注明岗位")
    df["skill"] = df["skill"].fillna("未注明技术")
    # 按岗位+技能去重（同一岗位同一技能组合只保留一条）
    df = df.drop_duplicates(subset=["position", "skill", "company"], keep="first")
    return df.reset_index(drop=True)

# openpyxl 视为非法的字符（含部分 Unicode 控制字符）
_ILLEGAL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u2028\u2029\u200b-\u200f\ufffe\uffff]")

def sanitize_for_export(df):
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_string_dtype(df[c]) or df[c].dtype == object:
            df[c] = df[c].map(
                lambda v: _ILLEGAL_RE.sub("", str(v))
                if isinstance(v, str) and _ILLEGAL_RE.search(v) else v)
    return df

# ============ 6. 导出 Excel ============
def export_excel(df, path):
    df = sanitize_for_export(df)
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="岗位技术明细", index=False)
        # 技能词频统计：把每个技能拆开计数
        counter = {}
        for s in df["skill"]:
            for x in str(s).split(", "):
                x = x.strip()
                if x and x != "未注明技术":
                    counter[x] = counter.get(x, 0) + 1
        freq = (pd.DataFrame(sorted(counter.items(), key=lambda kv: -kv[1]),
                             columns=["技术关键词", "出现次数"]))
        freq.to_excel(w, sheet_name="技能词频统计", index=False)
    print(f"✅ 已导出 Excel: {path} (共 {len(df)} 行)")

# ============ 7. 导出 SQL ============
def export_sql(df, path, table_name):
    df = sanitize_for_export(df)
    col_types = {}
    for col in df.columns:
        if pd.api.types.is_integer_dtype(df[col]):
            col_types[col] = "INTEGER"
        elif pd.api.types.is_float_dtype(df[col]):
            col_types[col] = "REAL"
        else:
            col_types[col] = "TEXT"
    create_sql = ("DROP TABLE IF EXISTS {t};\nCREATE TABLE {t} (\n".format(t=table_name)
                  + ",\n".join(f'    "{c}" {col_types[c]}' for c in df.columns)
                  + "\n);")
    lines = ["-- 就业数据清洗结果", create_sql, ""]
    quoted_cols = ", ".join(f'"{c}"' for c in df.columns)
    for _, row in df.iterrows():
        vals = []
        for col in df.columns:
            v = row[col]
            if pd.isna(v):
                vals.append("NULL")
            elif isinstance(v, (int, float)):
                vals.append(str(v))
            else:
                vals.append("'" + str(v).replace("'", "''") + "'")
        lines.append(f"INSERT INTO {table_name} ({quoted_cols}) VALUES ({', '.join(vals)});")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ 已导出 SQL: {path} (共 {len(df)} 条 INSERT)")

# ============ 8. 主流程 ============
def main():
    files = collect_input_files()
    if not files:
        print("❌ 未找到任何 csv/xlsx 输入文件")
        return
    frames = []
    for f in files:
        try:
            raw = load_one(f)
            print(f"📥 读取 {os.path.basename(f)}: {len(raw)} 行, {len(raw.columns)} 列")
            frames.append(normalize(raw, f))
        except Exception as e:
            print(f"⚠️ 跳过 {f}: {e}")
    if not frames:
        return
    df_all = pd.concat(frames, ignore_index=True)
    df_clean = clean_data(df_all)
    print(f"🧹 清洗完成: 合并 {len(df_all)} 行 → 剩余 {len(df_clean)} 行")

    export_excel(df_clean, OUTPUT_EXCEL)
    export_sql(df_clean, OUTPUT_SQL, TABLE_NAME)
    print("🎉 全部完成！")

if __name__ == "__main__":
    main()
