#!/usr/bin/env bash
# Ubuntu VPS 初回セットアップ（root または sudo で実行）
# 使い方:
#   sudo bash deploy/vps/setup-ubuntu.sh
# 事前にリポジトリを /var/www/freshberrymarket に clone しておくか、
# このスクリプトに GIT_REPO を渡してください。

set -euo pipefail

APP_DIR="${APP_DIR:-/var/www/freshberrymarket}"
GIT_REPO="${GIT_REPO:-https://github.com/misamisa683269/flask_FRESHBERRYMARKET_app.git}"
DOMAIN="${DOMAIN:-freshberrymarket.com}"

echo "==> パッケージ更新"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip nginx git curl

echo "==> アプリ配置: ${APP_DIR}"
mkdir -p "$(dirname "${APP_DIR}")"
if [[ ! -d "${APP_DIR}/.git" ]]; then
  git clone "${GIT_REPO}" "${APP_DIR}"
else
  git -C "${APP_DIR}" pull --ff-only || true
fi

cd "${APP_DIR}"
mkdir -p uploads

echo "==> Python venv / 依存関係"
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

if [[ ! -f .env ]]; then
  echo "==> .env が無いので .env.example から作成します（必ず中身を書き換えてください）"
  cp .env.example .env
  # ランダム SECRET_KEY
  SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env
fi

chown -R www-data:www-data "${APP_DIR}"
chmod 640 "${APP_DIR}/.env" || true

echo "==> systemd"
cp deploy/vps/freshberrymarket.service /etc/systemd/system/freshberrymarket.service
systemctl daemon-reload
systemctl enable freshberrymarket
systemctl restart freshberrymarket

echo "==> nginx"
cp deploy/vps/cloudflare-realip.conf /etc/nginx/conf.d/cloudflare-realip.conf
cp deploy/vps/nginx-freshberrymarket.conf /etc/nginx/sites-available/freshberrymarket
ln -sfn /etc/nginx/sites-available/freshberrymarket /etc/nginx/sites-enabled/freshberrymarket
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo ""
echo "==== セットアップ完了 ===="
echo "次にやること:"
echo "1) ${APP_DIR}/.env に Stripe キーなどを設定"
echo "   sudo nano ${APP_DIR}/.env && sudo systemctl restart freshberrymarket"
echo "2) Cloudflare DNS で ${DOMAIN} の A レコードをこの VPS の公開IPにする"
echo "   （Tunnel 用 CNAME があれば削除または無効化）"
echo "3) Cloudflare SSL/TLS モードは Full 推奨（Flexible でも暫定可）"
echo "4) 確認: curl -I http://127.0.0.1:8000/  と  https://${DOMAIN}/"
echo ""
systemctl --no-pager --full status freshberrymarket | head -20 || true
