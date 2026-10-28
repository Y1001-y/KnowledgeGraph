#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Qwen3-8B + Unsloth(4bit) 加载自测。

针对的报错：
  LocalEntryNotFoundError: Cannot find the requested files in the disk cache
  and outgoing traffic has been disabled.
  OSError: We couldn't connect to 'https://huggingface.co' ...
  PeftConfig error: Can't find 'adapter_config.json' at 'unsloth/Llama-3.2-1B-...'

这个脚本先做「模型到底在不在本地」的自检，再决定是否允许联网，
不会一上来就让 transformers 去撞离线墙。

用法：
  python test_load.py                                    # 自动探测本地模型
  MODEL_DIR=/home/yy/unsloth-work/models/Qwen3-8B python test_load.py
  ALLOW_DOWNLOAD=1 python test_load.py                   # 本地没有就联网下载(走镜像)

要点：
  * 本地目录必须是一个完整的 HF 快照：config.json + tokenizer* + *.safetensors
  * 不要用 bf16 原版 Qwen3-8B(约16GB) 在 12GB 卡上现场量化，用预量化的
    unsloth/Qwen3-8B-unsloth-bnb-4bit (约5GB) 更稳
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HOME = Path.home()

# ---------------- 配置 ----------------
MODEL_REPO = os.environ.get("MODEL_REPO", "unsloth/Qwen3-8B-unsloth-bnb-4bit")
HF_MIRROR = os.environ.get("HF_MIRROR", "https://hf-mirror.com")
MAX_SEQ_LENGTH = int(os.environ.get("MAX_SEQ_LENGTH", "512"))
LOAD_IN_4BIT = os.environ.get("LOAD_IN_4BIT", "1") == "1"
ALLOW_DOWNLOAD = os.environ.get("ALLOW_DOWNLOAD", "0") == "1"

# 候选本地路径，按优先级排列
CANDIDATES = [
    os.environ.get("MODEL_DIR", ""),
    str(HOME / "unsloth-work/models/Qwen3-8B-unsloth-bnb-4bit"),
    str(HOME / "unsloth-work/models/Qwen3-8B"),
    "/home/yy/unsloth-work/models/Qwen3-8B-unsloth-bnb-4bit",
    "/home/yy/unsloth-work/models/Qwen3-8B",
]

HF_CACHE = Path(
    os.environ.get("HUGGINGFACE_HUB_CACHE")
    or (Path(os.environ["HF_HOME"]) / "hub" if os.environ.get("HF_HOME") else HOME / ".cache/huggingface/hub")
)


# ---------------- 自检工具 ----------------
def inspect_model_dir(path: Path) -> tuple[bool, list[str]]:
    """检查目录是否是一个可直接被 transformers 加载的模型目录。"""
    msgs: list[str] = []
    ok = True

    if not path.is_dir():
        return False, [f"目录不存在: {path}"]

    cfg = path / "config.json"
    if cfg.is_file():
        msgs.append(f"  [OK] config.json ({cfg.stat().st_size} B)")
    else:
        ok = False
        msgs.append("  [缺失] config.json  <- 关键！没有它 transformers 不会把这里当模型目录")

    tok = [n for n in ("tokenizer_config.json", "tokenizer.json", "vocab.json", "merges.txt") if (path / n).is_file()]
    if tok:
        msgs.append(f"  [OK] tokenizer 文件: {', '.join(tok)}")
    else:
        ok = False
        msgs.append("  [缺失] tokenizer_config.json / tokenizer.json  <- 至少需要一个")

    weights = list(path.glob("*.safetensors")) + list(path.glob("pytorch_model*.bin"))
    if weights:
        total = sum(w.stat().st_size for w in weights) / 1024**3
        msgs.append(f"  [OK] 权重 {len(weights)} 个分片, 合计 {total:.2f} GB")
    else:
        ok = False
        msgs.append("  [缺失] 没有任何 *.safetensors 或 pytorch_model*.bin 权重")

    # 残留的未完成下载文件
    junk = list(path.glob("*.incomplete")) + list(path.glob("*.lock"))
    if junk:
        msgs.append(f"  [警告] 存在未完成/临时文件 {len(junk)} 个（可能是下载中断）")

    return ok, msgs


def print_dir_overview(base: Path) -> None:
    if not base.is_dir():
        print(f"  目录不存在: {base}")
        return
    entries = sorted(base.iterdir())
    if not entries:
        print(f"  (空目录) {base}")
        return
    for e in entries:
        kind = "DIR " if e.is_dir() else "FILE"
        try:
            size = sum(f.stat().st_size for f in e.rglob("*") if f.is_file()) / 1024**3 if e.is_dir() else e.stat().st_size / 1024**3
        except OSError:
            size = 0.0
        print(f"  {kind} {e.name:<45} {size:8.2f} GB")


def find_local_model() -> tuple[str | None, list[tuple[str, list[str]]]]:
    """返回 (可用的模型路径, 所有检查失败详情)"""
    problems: list[tuple[str, list[str]]] = []
    seen = set()
    for cand in CANDIDATES:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        p = Path(cand).expanduser()
        if not p.exists():
            continue
        ok, msgs = inspect_model_dir(p)
        print(f"\n检查本地模型目录: {p}")
        for m in msgs:
            print(m)
        if ok:
            return str(p.resolve()), problems
        problems.append((str(p), msgs))
    return None, problems


def fail(msg: str) -> None:
    print("\n" + "=" * 70)
    print(msg)
    print("=" * 70)
    sys.exit(1)


# ---------------- 主流程 ----------------
def main() -> None:
    print("=" * 70)
    print("环境变量现状")
    print("=" * 70)
    for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_ENDPOINT", "HF_HOME", "HF_HUB_CACHE"):
        print(f"  {k} = {os.environ.get(k, '<未设置>')}")
    print(f"  HF cache 目录 = {HF_CACHE}")

    model_path, problems = find_local_model()

    if model_path:
        # 本地可用：明确锁死离线，避免任何网络探测导致卡住
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        target = model_path
        local_only = True
        print(f"\n>>> 使用本地模型: {target}")
    elif ALLOW_DOWNLOAD:
        # 需要联网：必须先解除离线开关，否则一定报 LocalEntryNotFoundError
        for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
            os.environ.pop(k, None)
        os.environ.setdefault("HF_ENDPOINT", HF_MIRROR)
        target = MODEL_REPO
        local_only = False
        print(f"\n>>> 本地没有完整模型，改为联网加载仓库: {target}")
        print(f"    HF_ENDPOINT = {os.environ['HF_ENDPOINT']}")
    else:
        report = ["没有找到可直接加载的本地模型目录，且未开启 ALLOW_DOWNLOAD。",
                  "",
                  "已检查的位置："]
        for cand in CANDIDATES:
            if cand:
                report.append(f"  - {cand}")
        for path, msgs in problems:
            report.append("")
            report.append(f"目录 {path} 不合格：")
            report.extend(msgs)
        report += ["",
                   "本地 models 目录现状："]
        print("\n".join(report))
        print_dir_overview(HOME / "unsloth-work/models")
        print("\nHF 缓存里已有的仓库：")
        snap = HF_CACHE / "models--*"
        import glob as _glob
        found = _glob.glob(str(snap))
        print("\n".join(f"  {Path(f).name}" for f in found) if found else "  (无)")

        fail(
            "结论：模型文件不在本地。\n"
            f"  修法一（推荐，先下载再离线跑）：\n"
            f"    bash download_model.sh             # 下载 {MODEL_REPO} 到 ~/unsloth-work/models/\n"
            f"    python test_load.py\n"
            f"  修法二（直接联网加载，不落盘到本地目录）：\n"
            f"    unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE\n"
            f"    ALLOW_DOWNLOAD=1 python test_load.py\n"
            f"  注意：huggingface.co 在国内通常不可达，务必设 HF_ENDPOINT={HF_MIRROR}"
        )

    # ---------------- 导入（必须在环境变量确定之后） ----------------
    import torch

    if not torch.cuda.is_available():
        fail("torch.cuda.is_available() == False：当前装的是 CPU 版 torch，Unsloth 无法工作。\n"
             "RTX 5070 需要 CUDA 12.8 轮子，例如：\n"
             "  pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu128")

    props = torch.cuda.get_device_properties(0)
    print("\n" + "=" * 70)
    print("硬件 / 软件")
    print("=" * 70)
    print(f"  GPU        : {props.name}")
    print(f"  显存       : {props.total_memory / 1024**3:.2f} GB")
    print(f"  compute cap: sm_{props.major}{props.minor}")
    print(f"  torch      : {torch.__version__} (cuda {torch.version.cuda})")

    if props.major >= 12:
        print("  [提示] 这是 Blackwell 架构(sm_120)，torch 必须是 2.7+ / cu128 版本，否则会出现")
        print("         'CUDA error: no kernel image is available for execution on the device'")

    from unsloth import FastLanguageModel

    print("\n" + "=" * 70)
    print("开始加载模型")
    print("=" * 70)
    print(f"  model_name            = {target}")
    print(f"  use_exact_model_name  = {local_only}  (本地路径必须为 True，避免被重映射到 hub 仓库)")
    print(f"  max_seq_length        = {MAX_SEQ_LENGTH}")
    print(f"  load_in_4bit          = {LOAD_IN_4BIT}")
    print()

    # 注意：Unsloth 的参数名是 model_name，不是 model_name_or_path。
    # 后者会被 **kwargs 吞掉，导致 model_name 保持默认值(llama-3.2-1b)，于是去连 huggingface.co。
    load_kwargs = dict(
        model_name=target,
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=None,
        load_in_4bit=LOAD_IN_4BIT,
        local_files_only=local_only,
    )
    if local_only:
        # 本地目录名带 -unsloth-bnb-4bit 后缀，以免被 get_model_name() 剥后缀重新找仓库
        load_kwargs["use_exact_model_name"] = True

    try:
        model, tokenizer = FastLanguageModel.from_pretrained(**load_kwargs)
    except RuntimeError as e:
        msg = str(e)
        if "out of memory" in msg.lower() or "CUDA out of memory" in msg:
            fail("显存不足(OOM)。12GB 卡上建议：\n"
                 f"  1) 用预量化仓库 {MODEL_REPO}，别用 bf16 原版现场量化\n"
                 "  2) MAX_SEQ_LENGTH=256 再试一次\n"
                 "  3) 关掉其他占显存的进程：nvidia-smi")
        if "no kernel image" in msg.lower():
            fail("torch 与本卡(sm_120)不匹配：需要 torch 2.7+ 的 cu128 轮子。")
        if "huggingface.co" in msg or "adapter_config.json" in msg:
            fail("仍然去连了 huggingface.co —— 说明 model_name 没传进去，被回退成默认仓库了。\n"
                 "检查调用处是否误用了 model_name_or_path（Unsloth 只认 model_name）。")
        raise

    # ---------------- 加载后自检：确认加载的真是本地那个模型 ----------------
    loaded_id = str(getattr(model.config, "_name_or_path", "") or getattr(model.config, "name_or_path", ""))
    model_type = getattr(model.config, "model_type", "?")
    print("\nMODEL LOADED OK")
    print(f"  model_type   : {model_type}")
    print(f"  加载来源     : {loaded_id or '<空>'}")
    if local_only and "llama" in model_type.lower():
        fail("加载到了 Llama 而不是 Qwen3！说明 model_name 仍未生效，请检查是否还有别的地方覆盖了它。")
    print(f"GPU 已分配显存: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")
    print(f"tokenizer.vocab_size: {tokenizer.vocab_size}")

    # ---------------- 推理冒烟测试 ----------------
    prompts = ["Hello, who are you?"]
    for text in prompts:
        messages = [{"role": "user", "content": text}]
        try:
            # Qwen3 是思考型模型：enable_thinking=False 直接跳过 <think> 推理段，
            # 否则 64 个 token 全被思考过程吃掉，看不到正式回答
            inputs = tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                return_tensors="pt",
                enable_thinking=False,
            ).to("cuda")
        except Exception:
            inputs = tokenizer(text, return_tensors="pt").to("cuda")

        with torch.no_grad():
            outputs = model.generate(
                input_ids=inputs,
                max_new_tokens=128,
                do_sample=False,
                temperature=None,
                top_p=None,
            )
        new_tokens = outputs[0][inputs.shape[1]:]
        answer = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
        # 兜底：万一仍在思考模式，剥掉 <think>...</think> 只留正文
        if "</think>" in answer:
            answer = answer.split("</think>", 1)[1].strip()
        print("\n--- 输出 ---")
        print(answer)

    print(f"\n峰值显存: {torch.cuda.max_memory_allocated() / 1024**3:.2f} GB")
    print("\n全部通过 ✅")


if __name__ == "__main__":
    main()
