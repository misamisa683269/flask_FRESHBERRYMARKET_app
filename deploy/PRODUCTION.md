# 本番公開チェックリスト（Cloudflare Registrar + VPS）

このアプリを **Cursorを閉じても常時公開**するための、実装済み手順のまとめです。

## 最適構成

1. ドメイン: Cloudflare Registrar（取得済み想定: `freshberrymarket.com`）
2. アプリ: Ubuntu VPS 上の **Docker Compose**（推奨）または systemd+nginx
3. DNS: Cloudflare の A レコード → VPS IP（Proxied）
4. SSL: Cloudflare SSL/TLS = **Full**

## A. VPS（Docker）で起動【推奨】

VPS に Docker を入れたうえで:

```bash
git clone https://github.com/misamisa683269/flask_FRESHBERRYMARKET_app.git /var/www/freshberrymarket
cd /var/www/freshberrymarket
sudo bash deploy/vps/setup-docker.sh
sudo nano .env   # SECRET_KEY / Stripe / APP_ENV=production
docker compose up -d --build
curl -I http://127.0.0.1/health
```

関連ファイル:

- `docker-compose.yml`
- `Dockerfile`
- `deploy/vps/nginx-docker.conf`
- `deploy/vps/cloudflare-realip.conf`
- `deploy/vps/setup-docker.sh`

## B. VPS（systemd + nginx）でも可

```bash
sudo bash deploy/vps/setup-ubuntu.sh
```

詳細: `deploy/vps/README.md`

## C. Cloudflare DNS を VPS に向ける

Tunnel（自宅PC）から切り替える:

```bash
export CLOUDFLARE_API_TOKEN=...   # Zone.DNS Edit
export CLOUDFLARE_ZONE_ID=...     # Dashboard > ドメイン概要
export VPS_IP=x.x.x.x
./scripts/cloudflare-point-dns-to-vps.sh
```

または Dashboard で手動:

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| A | `@` | VPS IP | Proxied |
| A | `www` | VPS IP | Proxied |

Tunnel 用 CNAME（`*.cfargotunnel.com`）は削除。

Zone ID の場所: Cloudflare → Websites → freshberrymarket.com → Overview 右側。

## D. 本番 .env の要点

```bash
APP_ENV=production
SECRET_KEY=（24文字以上のランダム）
MAIL_SUPPRESS_SEND=true
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
DATABASE_PATH=/app/data/products.db   # Docker 時
```

`APP_ENV=production` のとき、弱い SECRET_KEY だとアプリは起動しません（安全装置）。

## E. 確認

- https://freshberrymarket.com/
- https://freshberrymarket.com/health → `{"status":"ok",...}`
- Stripe テスト決済（success URL が https ドメインになること）

## 実装できないこと（手元作業）

- VPS の契約・支払い
- Cloudflare へのログイン（トークンなしでは DNS 自動変更不可）
- 実カードでの本番決済（`sk_live_` は現行コードで拒否）

## 自宅 Tunnel との関係

開発・一時公開: `cloudflared tunnel run freshberrymarket`  
常時公開: 上記 VPS + DNS 切替後、自宅 Tunnel は停止してOK
