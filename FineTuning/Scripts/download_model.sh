#!/usr/bin/env bash
# 把模型下载成一个「完整的本地 HF 目录」，供离线加载使用。
#
# 用法：
#   bash download_model.sh                                         # 默认 unsloth/Qwen3-8B-unsloth-bnb-4bit
#   bash download_model.sh Qwen/Qwen3-8B                           # 指定仓库
#   bash download_model.sh unsloth/Qwen3-8B-unsloth-bnb-4bit /data/models/qwen3-8b-4bit
#
# 说明：
#   1. huggingface.co 在国内基本不可达，默认走 hf-mirror.com 镜像。
#   2. 必须禁用 Xet (HF_HUB_DISABLE_XET=1)。hf_xet 会走 cas-server.xethub.hf.co 这个
#      独立存储后端，镜像站不代理它，结果就是 401 Unauthorized / File reconstruction error。
#      禁用后退回普通 HTTP 分块下载，镜像才生效。

set -euo pipefail

REPO="${1:-unsloth/Qwen3-8B-unsloth-bnb-4bit}"
NAME="$(basename "$REPO")"
DEST="${2:-$HOME/unsloth-work/models/$NAME}"
RETRIES="${RETRIES:-3}"

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
# 关掉 Xet，否则镜像下载必然 401
export HF_HUB_DISABLE_XET=1
# 关掉 hf_transfer 的激进并发，镜像站容易限流
export HF_HUB_ENABLE_HF_TRANSFER=0
# 下载阶段必须解除离线开关，否则 hf_hub 只会翻本地缓存
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE

echo "仓库    : $REPO"
echo "目标    : $DEST"
echo "镜像    : $HF_ENDPOINT"
echo "Xet     : 已禁用 (HF_HUB_DISABLE_XET=1)"
df -h "$(dirname "$DEST")" | tail -1
echo

mkdir -p "$DEST"

download_once() {
  python - "$REPO" "$DEST" <<'PY'
import sys
from huggingface_hub import snapshot_download

repo, dest = sys.argv[1], sys.argv[2]
path = snapshot_download(
    repo_id=repo,
    local_dir=dest,
    max_workers=4,
    # 说明/示例图不必下载，省流量
    ignore_patterns=["*.md", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.pdf", ".gitattributes"],
)
print("\nDONE ->", path)
PY
}

attempt=1
while true; do
  echo "=== 第 $attempt/$RETRIES 次尝试 ==="
  if download_once; then
    break
  fi
  if [ "$attempt" -ge "$RETRIES" ]; then
    echo
    echo "!!! 下载失败 $RETRIES 次。排查建议："
    echo "    1) 确认已禁用 Xet: echo \$HF_HUB_DISABLE_XET   # 应为 1"
    echo "    2) 若仍报 401 from cas-server.xethub.hf.co，直接卸载 xet:"
    echo "         pip uninstall -y hf_xet hf-xet"
    echo "    3) 换镜像重试: HF_ENDPOINT=https://hf-mirror.com bash download_model.sh"
    echo "    4) 已下载的分片不会浪费，重跑会断点续传"
    exit 1
  fi
  attempt=$((attempt + 1))
  echo "第 $((attempt - 1)) 次失败，5 秒后重试（已下载部分会续传）..."
  sleep 5
done

echo
echo "=== 校验关键文件 ==="
missing=0
for f in config.json tokenizer_config.json; do
  if [ -f "$DEST/$f" ]; then
    echo "  [OK] $f"
  else
    echo "  [缺失] $f"
    missing=1
  fi
done
# tokenizer.json / vocab.json 视模型而定，有一个即可
if [ -f "$DEST/tokenizer.json" ] || [ -f "$DEST/vocab.json" ]; then
  echo "  [OK] tokenizer 词表文件"
else
  echo "  [警告] tokenizer.json / vocab.json 都没有"
  missing=1
fi
if compgen -G "$DEST/*.safetensors" > /dev/null; then
  ls -lh "$DEST"/*.safetensors | awk '{print "  [OK] 权重", $NF, $5}'
else
  echo "  [缺失] 没有任何 *.safetensors"
  missing=1
fi
# 清理下载中断留下的残留
find "$DEST" -name "*.incomplete" -o -name "*.lock" 2>/dev/null | head -5

echo
echo "总体积: $(du -sh "$DEST" | cut -f1)"
echo
if [ "$missing" -eq 0 ]; then
  echo "下一步: python test_load.py"
  echo "   或指定路径: MODEL_DIR=$DEST python test_load.py"
else
  echo "!!! 有文件缺失，先别急着加载，把上面的输出发出来看看"
  exit 1
fi
