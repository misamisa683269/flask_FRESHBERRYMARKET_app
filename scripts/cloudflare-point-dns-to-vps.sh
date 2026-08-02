#!/usr/bin/env bash
# Cloudflare DNS を VPS の A レコードへ切り替える
# 必要:
#   export CLOUDFLARE_API_TOKEN=...   # Zone.DNS Edit 権限
#   export CLOUDFLARE_ZONE_ID=...     # freshberrymarket.com の Zone ID
#   export VPS_IP=x.x.x.x
# 任意:
#   export DOMAIN=freshberrymarket.com
#
# 使い方:
#   ./scripts/cloudflare-point-dns-to-vps.sh

set -euo pipefail

DOMAIN="${DOMAIN:-freshberrymarket.com}"
: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN を設定してください}"
: "${CLOUDFLARE_ZONE_ID:?CLOUDFLARE_ZONE_ID を設定してください}"
: "${VPS_IP:?VPS_IP を設定してください}"

API="https://api.cloudflare.com/client/v4"
AUTH_HEADER=( -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" -H "Content-Type: application/json" )

upsert_a() {
  local name="$1"
  local fqdn="$2"
  echo "==> A ${name} -> ${VPS_IP}"

  local existing
  existing="$(curl -fsS "${AUTH_HEADER[@]}" \
    "${API}/zones/${CLOUDFLARE_ZONE_ID}/dns_records?type=A&name=${fqdn}" \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["result"][0]["id"] if d.get("result") else "")')"

  local payload
  payload="$(VPS_IP="${VPS_IP}" NAME="${name}" python3 - <<'PY'
import json, os
print(json.dumps({
  "type": "A",
  "name": os.environ["NAME"],
  "content": os.environ["VPS_IP"],
  "ttl": 1,
  "proxied": True
}))
PY
)"

  if [[ -n "${existing}" ]]; then
    curl -fsS -X PUT "${AUTH_HEADER[@]}" \
      --data "${payload}" \
      "${API}/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${existing}" >/dev/null
    echo "updated ${fqdn}"
  else
    curl -fsS -X POST "${AUTH_HEADER[@]}" \
      --data "${payload}" \
      "${API}/zones/${CLOUDFLARE_ZONE_ID}/dns_records" >/dev/null
    echo "created ${fqdn}"
  fi
}

delete_tunnel_cnames() {
  echo "==> Tunnel 用 CNAME を削除（あれば）"
  local json ids
  json="$(curl -fsS "${AUTH_HEADER[@]}" \
    "${API}/zones/${CLOUDFLARE_ZONE_ID}/dns_records?type=CNAME&per_page=100")"
  ids="$(echo "${json}" | DOMAIN="${DOMAIN}" python3 - <<'PY'
import json, os, sys
data = json.load(sys.stdin)
domain = os.environ["DOMAIN"]
www = "www." + domain
for r in data.get("result", []):
    name = r.get("name", "")
    content = r.get("content") or ""
    if name in {domain, www} and "cfargotunnel.com" in content:
        print(r["id"])
PY
)"
  for id in ${ids}; do
    [[ -z "${id}" ]] && continue
    curl -fsS -X DELETE "${AUTH_HEADER[@]}" \
      "${API}/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${id}" >/dev/null
    echo "deleted CNAME id=${id}"
  done
}

delete_tunnel_cnames
upsert_a "@" "${DOMAIN}"
upsert_a "www" "www.${DOMAIN}"

echo ""
echo "完了: https://${DOMAIN}/ が VPS(${VPS_IP}) を向くよう更新しました。"
echo "反映まで数分かかることがあります。SSL/TLS は Full 推奨です。"
