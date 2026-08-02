# FRESHBERRYMARKET — VPS 常時公開ガイド

Cursor や自宅PCを閉じてもサイトを開けるようにするための手順です。  
対象ドメイン例: `freshberrymarket.com`

**全体の最適手順まとめ:** [`../PRODUCTION.md`](../PRODUCTION.md)

## 全体像

1. Ubuntu VPS を契約する（お名前.com / さくらのVPS / ConoHa など）
2. **推奨:** Docker Compose で常時起動（`setup-docker.sh`）
3. または systemd + nginx（`setup-ubuntu.sh`）
4. Cloudflare DNS を「Tunnel（このPC）」から「VPS の IP」へ切り替える

## Docker Compose（推奨）

```bash
ssh root@あなたのVPSのIP
# Docker 導入後:
git clone https://github.com/misamisa683269/flask_FRESHBERRYMARKET_app.git /var/www/freshberrymarket
cd /var/www/freshberrymarket
sudo bash deploy/vps/setup-docker.sh
sudo nano .env
docker compose up -d --build
curl -I http://127.0.0.1/health
```

## systemd + nginx（Dockerなし）

```bash
ssh root@あなたのVPSのIP
git clone https://github.com/misamisa683269/flask_FRESHBERRYMARKET_app.git /var/www/freshberrymarket
cd /var/www/freshberrymarket
sudo bash deploy/vps/setup-ubuntu.sh
sudo nano /var/www/freshberrymarket/.env
sudo systemctl restart freshberrymarket
```

`.env` 最低限:

```bash
APP_ENV=production
SECRET_KEY=十分に長いランダム文字列
MAIL_SUPPRESS_SEND=true
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
```

## Cloudflare DNS を VPS に向ける（重要）

### 自動（APIトークンがある場合）

```bash
export CLOUDFLARE_API_TOKEN=...
export CLOUDFLARE_ZONE_ID=...
export VPS_IP=x.x.x.x
./scripts/cloudflare-point-dns-to-vps.sh
```

### 手動

Dashboard → **Websites** → `freshberrymarket.com` → **DNS**

1. Tunnel 用の **CNAME**（`xxxx.cfargotunnel.com`）があれば **削除**
2. **A レコード** を追加

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| A | `@` | VPSの公開IP | Proxied（オレンジ雲）推奨 |
| A | `www` | VPSの公開IP | Proxied 推奨 |

3. SSL/TLS → Overview で **Full**（推奨）

VPS 公開後は Mac の `cloudflared` / `python app.py` は停止してOKです。

## 更新

Docker:

```bash
cd /var/www/freshberrymarket && git pull && docker compose up -d --build
```

systemd:

```bash
cd /var/www/freshberrymarket && sudo bash deploy/vps/deploy.sh
```

## 注意

- SQLite / `uploads` / `data` は VPS ディスクに保存
- 本番 Stripe（`sk_live_`）はこの学習用設定のままでは使えません
