#!/usr/bin/env bash
# freshberrymarket.com をローカル Flask(8000) に Cloudflare Tunnel でつなぐ
set -euo pipefail

DOMAIN="${DOMAIN:-freshberrymarket.com}"
WWW_DOMAIN="${WWW_DOMAIN:-www.freshberrymarket.com}"
TUNNEL_NAME="${TUNNEL_NAME:-freshberrymarket}"
LOCAL_URL="${LOCAL_URL:-http://127.0.0.1:8000}"
CF_DIR="${HOME}/.cloudflared"

echo "==> 1) ローカルアプリ確認 (${LOCAL_URL})"
if ! curl -fsS -o /dev/null "${LOCAL_URL}/"; then
  echo "先に別ターミナルでアプリを起動してください: python app.py"
  exit 1
fi
echo "OK: アプリ応答あり"

echo "==> 2) Cloudflare ログイン（ブラウザが開きます）"
if [[ ! -f "${CF_DIR}/cert.pem" ]]; then
  cloudflared tunnel login
else
  echo "OK: 既存のログイン情報あり"
fi

echo "==> 3) トンネル作成 (${TUNNEL_NAME})"
if cloudflared tunnel list 2>/dev/null | grep -q "${TUNNEL_NAME}"; then
  echo "OK: トンネル既存"
else
  cloudflared tunnel create "${TUNNEL_NAME}"
fi

TUNNEL_ID="$(cloudflared tunnel list | awk -v name="${TUNNEL_NAME}" '$2==name {print $1; exit}')"
if [[ -z "${TUNNEL_ID}" ]]; then
  echo "トンネル ID を取得できませんでした"
  exit 1
fi
echo "OK: TUNNEL_ID=${TUNNEL_ID}"

echo "==> 4) DNS を ${DOMAIN} / ${WWW_DOMAIN} に紐づけ"
cloudflared tunnel route dns "${TUNNEL_NAME}" "${DOMAIN}" || true
cloudflared tunnel route dns "${TUNNEL_NAME}" "${WWW_DOMAIN}" || true

CONFIG_PATH="${CF_DIR}/config.yml"
echo "==> 5) ${CONFIG_PATH} を書き込み"
cat > "${CONFIG_PATH}" <<EOF
tunnel: ${TUNNEL_ID}
credentials-file: ${CF_DIR}/${TUNNEL_ID}.json

ingress:
  - hostname: ${DOMAIN}
    service: ${LOCAL_URL}
  - hostname: ${WWW_DOMAIN}
    service: ${LOCAL_URL}
  - service: http_status:404
EOF

echo "==> 6) トンネル起動"
echo "公開URL: https://${DOMAIN}"
echo "停止: Ctrl+C"
exec cloudflared tunnel run "${TUNNEL_NAME}"
