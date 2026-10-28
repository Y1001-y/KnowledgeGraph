#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
岗位数据集准备 + 技术技能抽取（为微调 Qwen3 构建 SFT 数据）

输入: BOSS直聘岗位 CSV (utf-8-sig, 125 列)

输出结构:
  <csv所在目录>/数据集/
    训练集/  训练集.csv  训练集.xlsx  train_sft_技能抽取.jsonl
    测试集/  测试集.csv  测试集.xlsx  test_sft_技能抽取.jsonl   (csv 前 n 行)
    技能统计.xlsx / 技能统计.csv          (全量技能出现次数)
  <csv所在目录>/<csv名>.xlsx              (全量转 Excel)

用法:
  python prepare_dataset.py                        # 默认前 1000 行做测试集
  python prepare_dataset.py --n 2000               # 自定义测试集行数
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

# ============================================================
# 技能词典: (规范名, 正则)  大小写不敏感，匹配范围 = 岗位名 + JD + 平台技能标签
# ============================================================
SKILLS: list[tuple[str, str]] = [
    # ---- 编程语言 ----
    ("Java",        r"\bjava\b(?!\s*script)"),
    ("Python",      r"\bpython\b"),
    ("C++",         r"c\s*\+\+"),
    ("C#",          r"c\s*#"),
    ("C语言",       r"c\s*语言|(?<![a-z0-9+#])c\s*(?=[/、，,和与])"),
    ("Go",          r"\bgolang\b|\bgo\b(?=\s*(?:语言|开发|后端|服务))"),
    ("Rust",        r"\brust\b"),
    ("Scala",       r"\bscala\b"),
    ("PHP",         r"\bphp\b"),
    ("JavaScript",  r"\bjava\s?script\b|\bjs\b"),
    ("TypeScript",  r"\btypescript\b"),
    ("Node.js",     r"node\.?js"),
    ("Kotlin",      r"\bkotlin\b"),
    ("Swift",       r"\bswift\b"),
    ("Objective-C", r"objective\s*-?\s*c"),
    ("R语言",       r"\br\s*语言\b"),
    ("MATLAB",      r"\bmatlab\b"),
    ("Lua",         r"\blua\b"),
    ("Perl",        r"\bperl\b"),
    ("Shell",       r"\bshell\b|shell\s*脚本"),
    ("SQL",         r"\bsql\b"),
    ("Groovy",      r"\bgroovy\b"),
    ("Dart",        r"\bdart\b"),
    ("Ruby",        r"\bruby\b"),
    ("VBA",         r"\bvba\b"),
    ("ABAP",        r"\babap\b"),
    ("Solidity",    r"\bsolidity\b"),
    # ---- 前端 ----
    ("Vue",         r"\bvue[23]?\b"),
    ("React",       r"\breact\b"),
    ("Angular",     r"\bangular\b"),
    ("HTML",        r"\bhtml\s?5?\b"),
    ("CSS",         r"\bcss\s?[23]?\b"),
    ("jQuery",      r"\bjquery\b"),
    ("小程序",      r"小程序"),
    ("uni-app",     r"uni-?app"),
    ("Flutter",     r"\bflutter\b"),
    ("Webpack",     r"\bwebpack\b"),
    ("Vite",        r"\bvite\b"),
    ("Electron",    r"\belectron\b"),
    ("Three.js",    r"three\.?js"),
    ("ECharts",     r"e\s?charts"),
    ("D3.js",       r"d3\.?js"),
    ("Sass/Less",   r"\bsass\b|\bless\b"),
    # ---- 后端/框架 ----
    ("Spring",      r"\bspring\s?(?:boot|cloud)?\b"),
    ("MyBatis",     r"\bmybatis\b|\bmybatis-?plus\b"),
    ("Django",      r"\bdjango\b"),
    ("Flask",       r"\bflask\b"),
    ("FastAPI",     r"\bfastapi\b"),
    ("Tornado",     r"\btornado\b"),
    ("Laravel",     r"\blaravel\b"),
    ("ThinkPHP",    r"\bthinkphp\b"),
    (".NET",        r"\.net\b|asp\.?net|\bnet\s?(?:core|[5-9])\b"),
    ("SSM",         r"\bssm\b"),
    ("Hibernate",   r"\bhibernate\b"),
    ("gRPC",        r"\bgrpc\b"),
    ("Dubbo",       r"\bdubbo\b"),
    ("RESTful",     r"\brestful\b|\brest\b(?=\s*(?:接口|api|ful))"),
    ("GraphQL",     r"\bgraphql\b"),
    ("微服务",      r"微服务"),
    ("分布式",      r"分布式"),
    ("高并发",      r"高并发"),
    ("多线程",      r"多线程"),
    ("中间件",      r"中间件"),
    # ---- 数据库/存储 ----
    ("MySQL",       r"\bmysql\b"),
    ("Oracle",      r"\boracle\b"),
    ("SQL Server",  r"sql\s?server|\bmssql\b"),
    ("PostgreSQL",  r"postgre\s?sql"),
    ("MongoDB",     r"\bmongo(?:db)?\b"),
    ("Redis",       r"\bredis\b"),
    ("Elasticsearch", r"elastic\s?search"),
    ("ClickHouse",  r"click\s?house"),
    ("Hive",        r"\bhive\b"),
    ("HBase",       r"\bhbase\b"),
    ("Cassandra",   r"\bcassandra\b"),
    ("Neo4j",       r"\bneo4j\b"),
    ("OceanBase",   r"\boceanbase\b"),
    ("TiDB",        r"\btidb\b"),
    ("SQLite",      r"\bsqlite\b"),
    ("Memcached",   r"\bmemcached\b"),
    ("InfluxDB",    r"\binfluxdb\b"),
    ("Doris",       r"\bdoris\b"),
    ("StarRocks",   r"\bstarrocks\b"),
    ("达梦",        r"达梦"),
    ("向量数据库",  r"向量数据库|向量库"),
    # ---- 大数据 ----
    ("Hadoop",      r"\bhadoop\b"),
    ("Spark",       r"\bspark\b"),
    ("Flink",       r"\bflink\b"),
    ("Kafka",       r"\bkafka\b"),
    ("RabbitMQ",    r"rabbit\s?mq"),
    ("RocketMQ",    r"rocket\s?mq"),
    ("Storm",       r"\bstorm\b"),
    ("Presto",      r"\bpresto\b|\btrino\b"),
    ("Kylin",       r"\bkylin\b"),
    ("Airflow",     r"\bairflow\b"),
    ("DataX",       r"\bdatax\b"),
    ("Kettle",      r"\bkettle\b"),
    ("Sqoop",       r"\bsqoop\b"),
    ("ZooKeeper",   r"zoo\s?keeper|\bzk\b"),
    ("DolphinScheduler", r"dolphin\s?scheduler"),
    ("Hudi",        r"\bhudi\b"),
    ("Iceberg",     r"\biceberg\b"),
    ("数据仓库",    r"数据仓库|数仓"),
    ("数据湖",      r"数据湖"),
    ("ETL",         r"\betl\b"),
    ("数据治理",    r"数据治理"),
    # ---- AI/机器学习 ----
    ("PyTorch",     r"py\s?torch"),
    ("TensorFlow",  r"tensor\s?flow"),
    ("Keras",       r"\bkeras\b"),
    ("Caffe",       r"\bcaffe\b"),
    ("MXNet",       r"\bmxnet\b"),
    ("PaddlePaddle", r"paddle\s?paddle|飞桨"),
    ("ONNX",        r"\bonnx\b"),
    ("OpenCV",      r"open\s?cv"),
    ("scikit-learn", r"scikit-?learn|sklearn"),
    ("XGBoost",     r"\bxgboost\b"),
    ("LightGBM",    r"\blightgbm\b"),
    ("Transformers", r"\btransformers?\b(?=\s*(?:库|框架))|hugging\s?face"),
    ("BERT",        r"\bbert\b"),
    ("GPT",         r"\bgpt\b"),
    ("大模型/LLM",  r"\bllm\b|大模型|千问|qwen|通义|文心|chatgpt"),
    ("Stable Diffusion", r"stable\s?diffusion"),
    ("YOLO",        r"\byolo\b"),
    ("RAG",         r"\brag\b"),
    ("LangChain",   r"lang\s?chain"),
    ("Milvus",      r"\bmilvus\b"),
    ("FAISS",       r"\bfaiss\b"),
    ("机器学习",    r"机器学习"),
    ("深度学习",    r"深度学习"),
    ("强化学习",    r"强化学习"),
    ("联邦学习",    r"联邦学习"),
    ("迁移学习",    r"迁移学习"),
    ("图神经网络",  r"图神经网络|\bgnn\b"),
    ("NLP",         r"\bnlp\b|自然语言处理"),
    ("计算机视觉",  r"计算机视觉|\bcv\b|图像(?:识别|处理|算法)"),
    ("OCR",         r"\bocr\b"),
    ("数据挖掘",    r"数据挖掘"),
    ("推荐系统",    r"推荐(?:系统|算法|引擎)"),
    ("知识图谱",    r"知识图谱"),
    ("AIGC",        r"\baigc\b"),
    ("多模态",      r"多模态"),
    ("目标检测",    r"目标检测"),
    ("语音识别",    r"语音识别|\basr\b"),
    ("语音合成",    r"语音合成|\btts\b"),
    ("智能体/Agent", r"智能体|\bai\s?agent\b|agent\s?开发"),
    ("Prompt工程",  r"prompt(?:工程|编写|调优|设计)"),
    ("数字人",      r"数字人"),
    # ---- 运维/云 ----
    ("Linux",       r"\blinux\b"),
    ("Unix",        r"\bunix\b"),
    ("Windows Server", r"windows\s?server"),
    ("Docker",      r"\bdocker\b"),
    ("Kubernetes",  r"\bk8s\b|kubernetes"),
    ("Jenkins",     r"\bjenkins\b"),
    ("Git/GitLab",  r"\bgit(?:lab|hub)?\b"),
    ("SVN",         r"\bsvn\b"),
    ("Ansible",     r"\bansible\b"),
    ("Terraform",   r"\bterraform\b"),
    ("Prometheus",  r"prometheus"),
    ("Grafana",     r"\bgrafana\b"),
    ("ELK",         r"\belk\b"),
    ("Nginx",       r"\bnginx\b"),
    ("Tomcat",      r"\btomcat\b"),
    ("CI/CD",       r"\bci\s?/\s?cd\b|持续集成|持续交付"),
    ("DevOps",      r"\bdevops\b"),
    ("阿里云",      r"阿里云"),
    ("腾讯云",      r"腾讯云"),
    ("华为云",      r"华为云"),
    ("AWS",         r"\baws\b"),
    ("Azure",       r"\bazure\b"),
    # ---- 测试/安全 ----
    ("Selenium",    r"\bselenium\b"),
    ("JMeter",      r"\bjmeter\b"),
    ("Postman",     r"\bpostman\b"),
    ("Appium",      r"\bappium\b"),
    ("LoadRunner",  r"load\s?runner"),
    ("pytest",      r"\bpytest\b"),
    ("自动化测试",  r"自动化测试"),
    ("性能测试",    r"性能测试"),
    ("渗透测试",    r"渗透测试"),
    ("网络安全",    r"网络安全"),
    ("Burp Suite",  r"burp\s?suite"),
    ("Wireshark",   r"\bwireshark\b"),
    ("Fiddler",     r"\bfiddler\b"),
    # ---- 嵌入式/客户端/其他 ----
    ("嵌入式",      r"嵌入式"),
    ("单片机",      r"单片机|\bmcu\b"),
    ("STM32",       r"\bstm32\b"),
    ("ARM",         r"\barm\b"),
    ("FPGA",        r"\bfpga\b"),
    ("PCB",         r"\bpcb\b"),
    ("ROS",         r"\bros\b"),
    ("SLAM",        r"\bslam\b"),
    ("Qt",          r"\bqt\b"),
    ("WinForm",     r"\bwinform\b"),
    ("WPF",         r"\bwpf\b"),
    ("MFC",         r"\bmfc\b"),
    ("LabVIEW",     r"\blabview\b"),
    ("Unity",       r"\bunity\b(?:\s*3d)?"),
    ("Unreal",      r"unreal\s?(?:engine)?"),
    ("Cocos",       r"\bcocos\b"),
    ("区块链",      r"区块链"),
    ("Web3",        r"\bweb3\b"),
    ("GIS",         r"\bgis\b|地理信息"),
    ("ArcGIS",      r"\barc\s?gis\b"),
    ("SAP",         r"\bsap\b"),
    ("用友",        r"用友"),
    ("金蝶",        r"金蝶"),
    ("Tableau",     r"\btableau\b"),
    ("PowerBI",     r"power\s?bi"),
    ("FineBI",      r"fine\s?bi"),
    ("FineReport",  r"fine\s?report"),
    ("Excel",       r"\bexcel\b"),
]

INSTRUCTION = "从下面的岗位信息中提取所有要求掌握的技术技能，只输出技能名称，用、分隔。"
JD_MAX_CHARS = 1200  # 截断过长 JD，适配 max_seq_length


def build_matchers():
    return [(name, re.compile(pat, re.IGNORECASE)) for name, pat in SKILLS]


def extract_skills(text: str, matchers) -> list[str]:
    """返回按词典顺序排列、去重后的技能列表"""
    if not isinstance(text, str):
        return []
    return [name for name, rx in matchers if rx.search(text)]


def parse_show_skills(raw) -> list[str]:
    """平台自带技能标签，形如 '测试开发; labview'"""
    if not isinstance(raw, str) or not raw.strip():
        return []
    parts = re.split(r"[;；,，]+", raw)
    return [p.strip() for p in parts if p.strip()]


def to_xlsx(df: pd.DataFrame, path: Path) -> None:
    """大表用 xlsxwriter constant_memory 快速写盘"""
    import xlsxwriter  # noqa: F401
    with pd.ExcelWriter(path, engine="xlsxwriter",
                        engine_kwargs={"options": {"constant_memory": True,
                                                   "strings_to_urls": False}}) as w:
        df.to_excel(w, index=False, sheet_name="data")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=r"D:\study\KnowledgeGraph\Origin data\3月新增-江苏-互联网AI.csv")
    ap.add_argument("--n", type=int, default=1000, help="前 n 行作为测试集")
    ap.add_argument("--out", default=r"D:\study\KnowledgeGraph\FineTuning\Datasets\Processed",
                    help="输出根目录，默认 FineTuning/Datasets/Processed")
    ap.add_argument("--skip-excel", action="store_true", help="跳过大 Excel 重写（已生成过时用）")
    ap.add_argument("--use-show-skills", action="store_true",
                    help="把平台 showSkills 标签并入标准答案（默认关闭：平台标签含大量非技能噪声，"
                         "如'工作简单''可带手机'，会污染训练标签）")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    out_root = Path(args.out)
    train_dir = out_root / "训练集"
    test_dir = out_root / "测试集"
    for d in (train_dir, test_dir):
        d.mkdir(parents=True, exist_ok=True)

    print(f"读取: {csv_path}")
    df = pd.read_csv(csv_path, dtype=str)
    total = len(df)
    print(f"原始数据: {total} 行 × {df.shape[1]} 列")

    # ---------- 0. 全量转 Excel ----------
    full_xlsx = csv_path.with_suffix(".xlsx")
    if args.skip_excel and full_xlsx.exists():
        print(f"跳过全量 Excel (已存在): {full_xlsx.name}")
    else:
        print(f"转换全量 Excel -> {full_xlsx.name} (2万行×125列，需要一点时间)...")
        to_xlsx(df, full_xlsx)

    # ---------- 1. 简单清洗 ----------
    n_no_jd = int(df["jobInfo_postDescription"].isna().sum())
    df = df[df["jobInfo_postDescription"].notna()].copy()
    n_dup = int(df.duplicated(subset=["jobInfo_jobName", "jobInfo_postDescription"]).sum())
    df_unique = df.drop_duplicates(subset=["jobInfo_jobName", "jobInfo_postDescription"]).copy()
    print(f"清洗: JD缺失 {n_no_jd} 行 | 完全重复岗位 {n_dup} 行 | 去重后 {len(df_unique)} 行")

    # ---------- 2. 训练/测试划分: 前 n 行测试集，其余训练集 ----------
    n = min(args.n, len(df))
    test_df = df.iloc[:n].copy()
    train_df = df.iloc[n:].copy()
    print(f"划分: 测试集 前 {len(test_df)} 行 | 训练集 其余 {len(train_df)} 行")

    test_df.to_csv(test_dir / "测试集.csv", index=False, encoding="utf-8-sig")
    train_df.to_csv(train_dir / "训练集.csv", index=False, encoding="utf-8-sig")
    if args.skip_excel and (test_dir / "测试集.xlsx").exists() and (train_dir / "训练集.xlsx").exists():
        print("跳过训练/测试集 Excel (已存在)")
    else:
        print("写出 Excel(测试集)..."); to_xlsx(test_df, test_dir / "测试集.xlsx")
        print("写出 Excel(训练集)..."); to_xlsx(train_df, train_dir / "训练集.xlsx")

    # ---------- 3. 技能抽取 ----------
    matchers = build_matchers()

    def count_skills(frame: pd.DataFrame) -> Counter:
        """按行计数：一个岗位里无论提到多少次，某技能只算 1"""
        c: Counter = Counter()
        for r in frame.itertuples():
            def sval(col):
                v = getattr(r, col, None)
                return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
            text = " ".join(filter(None, [sval("jobInfo_jobName"),
                                          sval("jobInfo_postDescription"),
                                          sval("jobInfo_showSkills")]))
            for s in extract_skills(text, matchers):
                c[s] += 1
            for s in parse_show_skills(sval("jobInfo_showSkills")):
                c[s] += 1
        return c

    counter_raw = count_skills(df)          # 口径一：全量原始行（含重复岗位）
    counter_uniq = count_skills(df_unique)  # 口径二：按岗位去重

    stat_df = pd.DataFrame({
        "技能": list(counter_raw.keys()),
        "出现次数(含重复岗位)": list(counter_raw.values()),
    })
    stat_df["出现次数(去重岗位)"] = stat_df["技能"].map(counter_uniq).fillna(0).astype(int)
    stat_df = stat_df.sort_values("出现次数(含重复岗位)", ascending=False).reset_index(drop=True)
    stat_df["占比-去重口径"] = (stat_df["出现次数(去重岗位)"] / len(df_unique) * 100).round(2)
    to_xlsx(stat_df, out_root / "技能统计.xlsx")
    stat_df.to_csv(out_root / "技能统计.csv", index=False, encoding="utf-8-sig")
    print(f"共识别技能 {len(stat_df)} 种，Top10(含重复口径): "
          + "、".join(f"{r.技能}({r._2})" for r in stat_df.head(10).itertuples()))
    print(f"Top10(去重口径): "
          + "、".join(f"{r.技能}({r._3}岗位, {r._4}%)" for r in stat_df.head(10).itertuples()))

    # ---------- 4. 生成 SFT 训练/测试样本 (jsonl) ----------
    freq_order = {s: i for i, s in enumerate(stat_df["技能"])}

    def make_sft(sub: pd.DataFrame, path: Path):
        cnt, dropped = 0, 0
        seen = set()
        with open(path, "w", encoding="utf-8") as f:
            for r in sub.itertuples():
                def sval(col):
                    v = getattr(r, col, None)
                    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
                job_name = sval("jobInfo_jobName").strip()
                jd = sval("jobInfo_postDescription").strip()
                show = sval("jobInfo_showSkills").strip()
                key = (job_name, jd)
                if key in seen:  # SFT 样本去重
                    dropped += 1
                    continue
                seen.add(key)
                if not jd:
                    dropped += 1
                    continue
                # 标签 = 纯词典抽取（岗位名+JD），默认不并入平台 showSkills 标签——
                # 平台标签混有"工作简单/可带手机"等非技能内容，会污染训练标签
                skills = extract_skills(" ".join(filter(None, [job_name, jd])), matchers)
                if args.use_show_skills:
                    skills += [s for s in parse_show_skills(show) if s not in skills]
                if not skills:
                    dropped += 1
                    continue
                skills.sort(key=lambda s: freq_order.get(s, 10**9))
                inp = (f"岗位名称：{getattr(r, 'jobInfo_jobName', '')}\n"
                       f"职位类别：{getattr(r, 'jobInfo_positionName', '')}\n"
                       f"岗位描述：{jd[:JD_MAX_CHARS]}")
                f.write(json.dumps({"instruction": INSTRUCTION,
                                    "input": inp,
                                    "output": "、".join(skills)},
                                   ensure_ascii=False) + "\n")
                cnt += 1
        return cnt, dropped

    c1, d1 = make_sft(train_df, train_dir / "train_sft_技能抽取.jsonl")
    c2, d2 = make_sft(test_df, test_dir / "test_sft_技能抽取.jsonl")
    print(f"SFT 训练样本: {c1} 条 (跳过 {d1}) -> {train_dir / 'train_sft_技能抽取.jsonl'}")
    print(f"SFT 测试样本: {c2} 条 (跳过 {d2}) -> {test_dir / 'test_sft_技能抽取.jsonl'}")

    print("\n完成 ✅")
    print(f"输出目录: {out_root}")


if __name__ == "__main__":
    main()
