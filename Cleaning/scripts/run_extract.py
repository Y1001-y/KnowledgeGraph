#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_extract.py — 抽取样本 → 云端 Qwen3-8B 清洗 → Excel 汇总

用法（在 Cleaning/ 目录下运行）:
  python scripts/run_extract.py                       全流程：txt → API → jsonl → Excel
  python scripts/run_extract.py --txt-only            只导出样本 txt，不调 API（没填 key 时先用这个）
  python scripts/run_extract.py --n 50                临时覆盖条数
  python scripts/run_extract.py --input "D:\\xx.csv"  临时覆盖输入文件

依赖（唯一一个第三方库）:
  pip install openpyxl -i https://mirrors.aliyun.com/pypi/simple/
  ※ 没装也能跑：Excel 环节自动降级为导出 CSV，其余功能不受影响

输出（全部落在 Cleaning/out/，文件名带时间戳，重复运行不会互相覆盖）:
  jd_sample_<N>_<时间戳>.txt        喂给模型的样本（人工核对用）
  skills_<时间戳>.jsonl             API 原始返回（一行一条，断点可续）
  extract_result_<时间戳>.xlsx      明细 + 技能频次两个 sheet
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

csv.field_size_limit(10 ** 7)

BASE_DIR = Path(__file__).resolve().parent.parent      # Cleaning/

# ════════════════════════════════════════════════════════════════
# 1. 需要你自己填写的配置（↓↓↓ 这五项 ↓↓↓）
# ════════════════════════════════════════════════════════════════

API_KEY = "sk-pduypieszmgdarbdoccgbzhffdwswuwwidwaaqbdtcsssaao"        # ← 填 sk- 开头的密钥。留空则依次尝试环境变量 LLM_API_KEY、同目录 .env 文件
BASE_URL = "https://api.siliconflow.cn/v1"        # 硅基流动（Qwen3-8B 免费）
                    # 阿里云百炼改成: "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL    = "Qwen/Qwen3-8B"                        # 百炼要改成: "qwen3-8b"
                    # ※ 两个平台都不能直接写 "Qwen3-8B"，会 404
INPUT_CSV = r"D:\study\KnowledgeGraph\Origin data\3月新增-江苏-互联网AI.csv"     # ← 填原始数据路径，例:
                    #    r"D:\study\KnowledgeGraph\Origin data\3月新增-江苏-互联网AI.csv"
N         = 30      # 默认抽取条数（命令行 --n 可临时覆盖）
ID_PREFIX = "3yxz"  # job_id 前缀，与 eval/jd-sample-10.txt 保持同一套编号

# ---- 以下参数一般不用动（与 config.yaml 保持一致）----
TEMPERATURE     = 0.0     # 抽取必须锁 0，否则每轮结果不可比
TOP_P           = 1.0
MAX_TOKENS      = 512
ENABLE_THINKING = False   # Qwen3 思考模式必须关，否则 JSON 里混入思考过程
JD_MAX_CHARS    = 3000    # JD 截断长度，8B 对长文尾部技能易漏
TIMEOUT         = 60      # 单次请求超时（秒）
MAX_RETRY       = 5       # 失败重试次数（指数退避 2s/4s/8s/16s/32s）
RETRY_BASE      = 2.0

PROMPT_FILE = BASE_DIR / "prompts" / "extract_skills.md"
BLOCKLIST_FILE = BASE_DIR / "rules" / "blocklist.yaml"
ALIAS_FILE = BASE_DIR / "rules" / "alias_map.yaml"
OUT_DIR     = BASE_DIR / "out"
# ════════════════════════════════════════════════════════════════


# ----------------------------------------------------------------
# 配置解析
# ----------------------------------------------------------------

def resolve_api_key() -> str:
    """填了 API_KEY 就用它；否则读环境变量 LLM_API_KEY；再否则读 Cleaning/.env。"""
    if API_KEY:
        return API_KEY.strip()
    env = os.environ.get("LLM_API_KEY", "").strip()
    if env:
        return env
    dot_env = BASE_DIR / ".env"
    if dot_env.exists():
        for line in dot_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("LLM_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


# ----------------------------------------------------------------
# 读取原始数据
# ----------------------------------------------------------------

# 两套字段名自动适配：BOSS 宽表（125 列）优先，其次中文简洁表（5 列）
FIELD_MAPS = [
    {"name": "jobInfo_jobName", "jd": "jobInfo_postDescription", "skills": "jobInfo_showSkills"},
    {"name": "岗位名称",         "jd": "岗位描述",                 "skills": "岗位技能"},
]


def detect_fields(sample_row: dict) -> dict:
    for m in FIELD_MAPS:
        if m["jd"] in sample_row:
            return m
    raise SystemExit(f"无法识别 CSV 字段。表头里有这些列：{list(sample_row)[:10]} ...")


def load_rows(path: str, n: int) -> list:
    """读前 n 条「岗位描述非空」的记录，按原始顺序。"""
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"输入文件不存在：{p}")
    rows, fields = [], None
    with open(p, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if fields is None:
                fields = detect_fields(row)
            jd = (row.get(fields["jd"]) or "").strip()
            if not jd:
                continue
            rows.append({
                "name": (row.get(fields["name"]) or "").strip(),
                "skills": (row.get(fields["skills"]) or "").strip(),
                "jd": jd[:JD_MAX_CHARS],
            })
            if len(rows) >= n:
                break
    if not rows:
        raise SystemExit("没有读到任何「岗位描述非空」的行，请检查输入文件。")
    return rows


def build_user_text(idx: int, row: dict) -> str:
    """拼用户消息，格式与 eval/jd-sample-10.txt 完全一致。"""
    lines = [f"job_id: {ID_PREFIX}-{idx:03d}"]
    if row["name"]:
        lines.append(f"岗位名称: {row['name']}")
    if row["skills"]:
        lines.append(f"【候选技能】{row['skills']}")
    lines.append("JD:")
    lines.append(row["jd"])
    return "\n".join(lines)


# ----------------------------------------------------------------
# 导出样本 txt（带时间戳，避免覆盖）
# ----------------------------------------------------------------

def write_txt(rows: list, texts: list, stamp: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"jd_sample_{len(rows)}_{stamp}.txt"
    with open(path, "w", encoding="utf-8-sig", newline="\n") as f:
        f.write(f"样本 {len(rows)} 条（生成于 {stamp}，来源见 run 日志）\n")
        f.write("用法：一次复制一条（从 job_id 行到末尾），粘进对话框。一次只喂一条。\n")
        f.write("=" * 60 + "\n")
        for i, t in enumerate(texts, 1):
            f.write(f"\n【第 {i} 条】\n" + "-" * 60 + "\n")
            f.write(t + "\n")
    return path


# ----------------------------------------------------------------
# 调用云端 API（urllib 标准库，绕开本机代理）
# ----------------------------------------------------------------

# 显式禁用系统代理：本机若挂了 SteamTools / Clash 的 MITM 代理，会拦掉 HTTPS 导致证书报错
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call_api(system_prompt: str, user_text: str) -> str:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": TEMPERATURE,
        "top_p": TOP_P,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    if not ENABLE_THINKING:
        payload["enable_thinking"] = False
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    last_err = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            with OPENER.open(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
            retryable = e.code in (429, 500, 502, 503, 504)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as e:
            last_err = f"{type(e).__name__}: {e}"
            retryable = True
        if retryable and attempt < MAX_RETRY:
            wait = RETRY_BASE * (2 ** (attempt - 1))
            print(f"    第 {attempt} 次失败（{last_err}），{wait:.0f}s 后重试")
            time.sleep(wait)
    raise RuntimeError(f"重试 {MAX_RETRY} 次仍失败：{last_err}")


def parse_reply(raw: str) -> list:
    """容错解析：剥 ```json 代码块 → 取 skills 数组 → 只留非空字符串。"""
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt).strip()
    data = json.loads(txt)
    skills = data.get("skills", [])
    if not isinstance(skills, list):
        raise ValueError("skills 不是数组")
    return [s.strip() for s in skills if isinstance(s, str) and s.strip()]


# ----------------------------------------------------------------
# 后处理黑名单（rules/blocklist.yaml，迷你解析器，不依赖 pyyaml）
# 只识别两类行：`action: drop|flag` 和列表项 `- 词`；遇到顶层键即离开当前类。
# ----------------------------------------------------------------

def _norm(t: str) -> str:
    """匹配口径：去空白 + 忽略大小写（KPI/kpi 等价，汉字不受影响）。"""
    return re.sub(r"\s+", "", t).casefold()


def load_blocklist(path: Path) -> tuple[set, set]:
    drop, flag, action = set(), set(), None
    if not path.exists():
        return drop, flag
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].rstrip()          # 去注释
        if not line.strip():
            continue
        if not line[:1].isspace():                     # 顶层键（mode:/categories:/review_log:）
            action = None
            continue
        m = re.match(r"^\s*action:\s*(drop|flag)\s*$", line)
        if m:
            action = m.group(1)
            continue
        m = re.match(r"^\s*-\s+(\S.*)$", line)
        if m and action:
            term = m.group(1).strip().strip("\"'")
            if term:
                (drop if action == "drop" else flag).add(_norm(term))
    return drop, flag


# ----------------------------------------------------------------
# 别名归一（rules/alias_map.yaml，迷你解析器，不依赖 pyyaml）
# Mysql / mysql → MySQL，VUE → Vue……大小写变体在此自动归并，无需人工复核。
# ----------------------------------------------------------------

def load_alias_map(path: Path) -> dict:
    """只读 aliases: 区的 `规范名: [变体, ...]` 行，返回 {归一化写法: 规范名}。"""
    mapping, in_aliases = {}, False
    if not path.exists():
        return mapping
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():                     # 顶层键，切换区域
            in_aliases = line.split(":", 1)[0].strip() == "aliases"
            continue
        if not in_aliases:
            continue
        m = re.match(r"^\s*(.+?):\s*\[(.*)\]\s*$", line.split("#", 1)[0].rstrip())
        if not m:
            continue
        canonical, variants = m.group(1).strip(), m.group(2)
        mapping[_norm(canonical)] = canonical
        for v in variants.split(","):
            v = v.strip().strip("\"'")
            if v:
                mapping[_norm(v)] = canonical
    return mapping


# ----------------------------------------------------------------
# 导出 Excel（openpyxl 缺失时降级 CSV）
# ----------------------------------------------------------------

def write_excel(rows, results, stamp):
    try:
        from openpyxl import Workbook
        from openpyxl.utils import get_column_letter
    except ImportError:
        return write_csv(rows, results, stamp)

    wb = Workbook()

    # ---- sheet1 岗位明细 ----
    ws = wb.active
    ws.title = "岗位明细"
    ws.append(["job_id", "岗位名称", "模型抽取技能", "技能数", "被黑名单过滤", "待人工复核(flag)", "候选技能", "状态"])
    for row, (text, res) in zip(rows, results):
        ws.append([
            res["job_id"], row["name"], "、".join(res["skills"]),
            len(res["skills"]), "、".join(res.get("dropped", [])),
            "、".join(res.get("flagged", [])), row["skills"], res["status"],
        ])
    for col, w in zip("ABCDEFGH", (10, 28, 60, 8, 24, 24, 30, 12)):
        ws.column_dimensions[col].width = w

    # ---- sheet2 技能频次 ----
    freq, ok_count = {}, 0
    for _, res in results:
        if res["status"] == "成功":
            ok_count += 1
            for s in res["skills"]:
                freq[s] = freq.get(s, 0) + 1
    ws2 = wb.create_sheet("技能频次")
    ws2.append(["技能", "出现岗位数", "占成功条数比"])
    for skill, cnt in sorted(freq.items(), key=lambda x: -x[1]):
        ws2.append([skill, cnt, f"{cnt / ok_count:.1%}" if ok_count else ""])
    for col, w in zip("ABC", (30, 12, 14)):
        ws2.column_dimensions[col].width = w

    path = OUT_DIR / f"extract_result_{stamp}.xlsx"
    wb.save(path)
    return path


def write_csv(rows, results, stamp):
    """openpyxl 未安装时的降级输出（内容与 Excel 相同，两个文件）。"""
    p1 = OUT_DIR / f"extract_result_{stamp}_明细.csv"
    with open(p1, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["job_id", "岗位名称", "模型抽取技能", "技能数", "被黑名单过滤", "待人工复核(flag)", "候选技能", "状态"])
        for row, (text, res) in zip(rows, results):
            w.writerow([res["job_id"], row["name"], "、".join(res["skills"]),
                        len(res["skills"]), "、".join(res.get("dropped", [])),
                        "、".join(res.get("flagged", [])), row["skills"], res["status"]])
    print(f"  ※ 未安装 openpyxl，已降级输出 CSV。安装后重跑可得 Excel：pip install openpyxl")
    return p1


# ----------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------

def main():
    global api_key
    ap = argparse.ArgumentParser(description="JD 技能抽取：txt 样本 → 云端清洗 → Excel")
    ap.add_argument("--input", default=INPUT_CSV, help="原始数据 csv 路径")
    ap.add_argument("--n", type=int, default=N, help="抽取条数（默认 30）")
    ap.add_argument("--txt-only", action="store_true", help="只导出样本 txt，不调 API")
    args = ap.parse_args()

    if not args.input:
        raise SystemExit("未指定输入文件：请在脚本顶部 INPUT_CSV 填路径，或用 --input 传入")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = load_rows(args.input, args.n)
    texts = [build_user_text(i, r) for i, r in enumerate(rows)]

    txt_path = write_txt(rows, texts, stamp)
    print(f"[1/3] 样本已导出：{txt_path.name}（{len(rows)} 条）")
    if args.txt_only:
        print("已按 --txt-only 结束，未调用 API。")
        return

    api_key = resolve_api_key()
    if not api_key:
        raise SystemExit(
            "缺少 API Key。三选一：\n"
            "  ① 脚本顶部 API_KEY = \"sk-...\" 直接填\n"
            "  ② 设置环境变量 set LLM_API_KEY=sk-...\n"
            "  ③ 在 Cleaning/.env 里写一行 LLM_API_KEY=sk-..."
        )
    if not PROMPT_FILE.exists():
        raise SystemExit(f"找不到 prompt 文件：{PROMPT_FILE}")
    system_prompt = PROMPT_FILE.read_text(encoding="utf-8")

    block_drop, block_flag = load_blocklist(BLOCKLIST_FILE)
    alias_index = load_alias_map(ALIAS_FILE)
    if block_drop or block_flag:
        print(f"黑名单已加载：drop {len(block_drop)} 项 / flag {len(block_flag)} 项")
    else:
        print("※ 未找到黑名单或其为空，跳过后处理过滤")
    if alias_index:
        print(f"别名表已加载：{len(alias_index)} 个写法将自动归并（Mysql→MySQL、VUE→Vue …）")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = OUT_DIR / f"skills_{stamp}.jsonl"
    results, ok, fail = [], 0, 0
    with open(jsonl_path, "w", encoding="utf-8", newline="\n") as jf:
        for i, (row, text) in enumerate(zip(rows, texts)):
            job_id = f"{ID_PREFIX}-{i:03d}"
            print(f"[2/3] ({i + 1}/{len(rows)}) {job_id} {row['name'][:20]} ...", end=" ", flush=True)
            try:
                raw = call_api(system_prompt, text)
                # ① 别名归一（Mysql→MySQL），② 归一后去重，③ 黑名单过滤
                skills = [alias_index.get(_norm(s), s) for s in parse_reply(raw)]
                seen = set()
                deduped = []
                for s in skills:
                    if s not in seen:
                        seen.add(s)
                        deduped.append(s)
                skills = deduped
                dropped = [s for s in skills if _norm(s) in block_drop]
                flagged = [s for s in skills
                           if _norm(s) not in block_drop and _norm(s) in block_flag]
                kept = [s for s in skills if _norm(s) not in block_drop]
                res = {"job_id": job_id, "skills": kept, "dropped": dropped,
                       "flagged": flagged, "status": "成功"}
                ok += 1
                note = f"{len(kept)} 项技能"
                if dropped:
                    note += f"（黑名单过滤 {len(dropped)}）"
                print(note)
            except Exception as e:
                res = {"job_id": job_id, "skills": [], "dropped": [],
                       "flagged": [], "status": f"失败: {e}"}
                fail += 1
                print("失败")
            results.append((text, res))
            jf.write(json.dumps(res, ensure_ascii=False) + "\n")
            jf.flush()   # 每条立即落盘，中断后已完成的不丢

    xlsx_path = write_excel(rows, results, stamp)
    total_dropped = sum(len(r.get("dropped", [])) for _, r in results)
    total_flagged = sum(len(r.get("flagged", [])) for _, r in results)
    print(f"[3/3] Excel 已输出：{xlsx_path}")
    print(f"\n完成：成功 {ok} / 失败 {fail}；黑名单过滤 {total_dropped} 项，待复核 {total_flagged} 项")
    print(f"产物：\n  样本   {txt_path}\n  原始   {jsonl_path}\n  汇总   {xlsx_path}")


if __name__ == "__main__":
    main()
