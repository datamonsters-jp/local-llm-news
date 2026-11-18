#!/usr/bin/env bash
# LOCAL LLM NEWS — 手元のマシン（Mac mini など）で毎朝実行するためのスクリプト
#
#   1) 最新の main を取得
#   2) update_news.py でローカルLLM（DGX Spark の GLM など）に更新させる
#   3) news.json が変わっていればコミットして push（→ GitHub Pages に反映）
#
# 設定は scripts/.env に書きます（scripts/.env.example をコピー）。
# cron 例（毎朝7:00 JST、マシンのタイムゾーンがJSTの場合）:
#   0 7 * * * /path/to/local-llm-news/scripts/run_local.sh >> /tmp/local-llm-news.log 2>&1
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

if [ -f scripts/.env ]; then
  set -a; . scripts/.env; set +a
fi

PYTHON="${PYTHON:-python3}"
if [ -x "$REPO_DIR/.venv/bin/python" ]; then
  PYTHON="$REPO_DIR/.venv/bin/python"
fi

echo "=== $(date '+%Y-%m-%d %H:%M:%S') LOCAL LLM NEWS update ==="

# LLMサーバーが起きているか先に確認（落ちていたら何もしない）
if ! curl -fsS -m 10 ${LLM_API_KEY:+-H "Authorization: Bearer $LLM_API_KEY"} "${LLM_BASE_URL%/}/models" > /dev/null; then
  echo "LLMサーバー(${LLM_BASE_URL})に接続できないため中止します"
  exit 1
fi

git pull --ff-only --quiet

"$PYTHON" update_news.py

git add news.json
if git diff --cached --quiet; then
  echo "No changes to commit."
else
  git -c user.name="local-llm-news-bot" -c user.email="actions@github.com" \
    commit -m "🤖 news: $(TZ=Asia/Tokyo date +%Y.%m.%d) 自動更新" --quiet
  git push --quiet
  echo "pushed."
fi
