#!/usr/bin/env bash
# VPS 上でコードを更新して再起動する
# 使い方（VPS 上）: sudo bash deploy/vps/deploy.sh

set -euo pipefail

APP_DIR="${APP_DIR:-/var/www/freshberrymarket}"
cd "${APP_DIR}"

echo "==> git pull"
git pull --ff-only

echo "==> 依存関係"
./.venv/bin/pip install -r requirements.txt

echo "==> 権限"
mkdir -p uploads
chown -R www-data:www-data "${APP_DIR}"
chmod 640 "${APP_DIR}/.env" || true

echo "==> 再起動"
systemctl restart freshberrymarket
systemctl reload nginx || true

echo "OK: $(systemctl is-active freshberrymarket)"
curl -fsS -o /dev/null -w "local:%{http_code}\n" http://127.0.0.1:8000/ || true
