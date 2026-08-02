#!/usr/bin/env bash
# VPS 初回セットアップ（root で実行）
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "==> 1) 基本パッケージ"
apt-get update -y
apt-get install -y ca-certificates curl git

echo "==> 2) Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
docker --version
docker compose version

APP_DIR=/var/www/freshberrymarket
REPO=https://github.com/misamisa683269/flask_FRESHBERRYMARKET_app.git

echo "==> 3) アプリ配置"
mkdir -p /var/www
if [[ ! -d "${APP_DIR}/.git" ]]; then
  git clone "${REPO}" "${APP_DIR}"
else
  git -C "${APP_DIR}" pull --ff-only || true
fi
cd "${APP_DIR}"
bash deploy/vps/setup-docker.sh

echo "==> 4) ローカル疎通"
curl -fsS -o /dev/null -w "health:%{http_code}\n" http://127.0.0.1/health || true
docker compose ps

echo ""
echo "完了。次は Cloudflare DNS を 163.44.124.60 に向けます。"
