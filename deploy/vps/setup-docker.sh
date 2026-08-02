#!/usr/bin/env bash
# VPS 上で Docker Compose による常時公開（推奨・実装済み構成）
set -euo pipefail

APP_DIR="${APP_DIR:-/var/www/freshberrymarket}"
GIT_REPO="${GIT_REPO:-https://github.com/misamisa683269/flask_FRESHBERRYMARKET_app.git}"

echo "==> Docker / Compose 確認"
command -v docker >/dev/null || { echo "docker をインストールしてください"; exit 1; }
docker compose version >/dev/null

echo "==> アプリ配置: ${APP_DIR}"
mkdir -p "$(dirname "${APP_DIR}")"
if [[ ! -d "${APP_DIR}/.git" ]]; then
  git clone "${GIT_REPO}" "${APP_DIR}"
else
  git -C "${APP_DIR}" pull --ff-only || true
fi

cd "${APP_DIR}"
mkdir -p data uploads
# コンテナ内 appuser (uid 10001) が書き込めるようにする
chown -R 10001:10001 data uploads || true

if [[ ! -f .env ]]; then
  cp .env.example .env
  SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  if grep -q '^SECRET_KEY=' .env; then
    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env
  else
    echo "SECRET_KEY=${SECRET}" >> .env
  fi
  if grep -q '^APP_ENV=' .env; then
    sed -i 's|^APP_ENV=.*|APP_ENV=production|' .env
  else
    echo "APP_ENV=production" >> .env
  fi
  echo ".env を作成しました。Stripe キーを追記してください。"
fi

echo "==> ビルド & 起動"
docker compose pull || true
docker compose up -d --build

echo ""
echo "==== Docker 起動完了 ===="
echo "次:"
echo "1) nano ${APP_DIR}/.env で Stripe キーを設定し、docker compose up -d --build"
echo "2) Cloudflare DNS を VPS IP の A レコードへ（scripts/cloudflare-point-dns-to-vps.sh）"
echo "3) curl -I http://127.0.0.1/health"
docker compose ps
