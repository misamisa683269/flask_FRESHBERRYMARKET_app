#!/usr/bin/env bash
# Flask(8000) + Cloudflare Named Tunnel を1組だけ起動し、公開URLを確認する
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DOMAIN="${DOMAIN:-freshberrymarket.com}"
TUNNEL_NAME="${TUNNEL_NAME:-freshberrymarket}"
LOCAL_URL="${LOCAL_URL:-http://127.0.0.1:8000}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
APP_LOG="${APP_LOG:-/tmp/freshberrymarket-app.log}"
TUNNEL_LOG="${TUNNEL_LOG:-/tmp/freshberrymarket-tunnel.log}"

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: $PYTHON がありません。先に: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

if [[ ! -f "$HOME/.cloudflared/config.yml" ]]; then
  echo "ERROR: ~/.cloudflared/config.yml がありません。"
  echo "先に: ./scripts/setup-cloudflare-tunnel.sh"
  exit 1
fi

echo "==> 1) 重複 cloudflared を停止（1本だけにする）"
pkill -f "cloudflared tunnel run ${TUNNEL_NAME}" 2>/dev/null || true
pkill -f "cloudflared tunnel --url" 2>/dev/null || true
sleep 1

echo "==> 2) Flask (${LOCAL_URL})"
if curl -fsS -o /dev/null --max-time 3 "${LOCAL_URL}/"; then
  echo "OK: すでに起動中"
else
  echo "起動: ${PYTHON} app.py"
  nohup "$PYTHON" app.py >"$APP_LOG" 2>&1 &
  for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null --max-time 2 "${LOCAL_URL}/"; then
      break
    fi
    sleep 0.5
  done
  if ! curl -fsS -o /dev/null --max-time 3 "${LOCAL_URL}/"; then
    echo "ERROR: Flask が起動しません。ログ: $APP_LOG"
    tail -n 40 "$APP_LOG" || true
    exit 1
  fi
  echo "OK: Flask 起動"
fi

echo "==> 3) Tunnel (${TUNNEL_NAME}) をフォアグラウンド起動"
echo "公開URL: https://${DOMAIN}"
echo "停止: Ctrl+C（Tunnelのみ停止。Flaskは残る場合あり）"
echo "Tunnelログも表示します..."
echo

# 起動直後に公開URLを裏で確認
(
  sleep 8
  code="$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "https://${DOMAIN}/health" || true)"
  if [[ "$code" == "200" ]]; then
    echo ""
    echo "==> 公開確認 OK: https://${DOMAIN}/health → ${code}"
  else
    echo ""
    echo "==> 公開確認: https://${DOMAIN}/health → ${code:-timeout}（数秒待って再読込してください）"
  fi
) &

exec cloudflared tunnel run "$TUNNEL_NAME"
