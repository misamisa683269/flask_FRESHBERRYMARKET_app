# FRESHBERRYMARKET — VPS 常時公開ガイド

Cursor や自宅PCを閉じてもサイトを開けるようにするための手順です。  
対象ドメイン例: `freshberrymarket.com`

## 全体像

1. Ubuntu VPS を契約する（お名前.com / さくらのVPS / ConoHa など）
2. VPS にアプリを入れて gunicorn + nginx + systemd で常時起動
3. Cloudflare DNS を「Tunnel（このPC）」から「VPS の IP」へ切り替える

## 0. 用意するもの

- VPS（Ubuntu 22.04 / 24.04 推奨）
- root または sudo できる SSH
- GitHub リポジトリ（公開でOK）
- Cloudflare の `freshberrymarket.com` ゾーン
- `.env` 用の `SECRET_KEY` / Stripe テストキー

## 1. VPS にログイン

```bash
ssh root@あなたのVPSのIP
```

## 2. 初回セットアップ

```bash
git clone https://github.com/misamisa683269/flask_FRESHBERRYMARKET_app.git /var/www/freshberrymarket
cd /var/www/freshberrymarket
sudo bash deploy/vps/setup-ubuntu.sh
```

## 3. 環境変数

```bash
sudo nano /var/www/freshberrymarket/.env
```

最低限:

```bash
SECRET_KEY=十分に長いランダム文字列
MAIL_SUPPRESS_SEND=true
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
```

反映:

```bash
sudo systemctl restart freshberrymarket
```

## 4. Cloudflare DNS を VPS に向ける（重要）

Dashboard → **Websites** → `freshberrymarket.com` → **DNS**

### やること

1. Tunnel 用の **CNAME**（`freshberrymarket.com` → `xxxx.cfargotunnel.com`）があれば **削除**
2. 次の **A レコード** を追加（または編集）

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| A | `@` | VPSの公開IP | Proxied（オレンジ雲）推奨 |
| A | `www` | VPSの公開IP | Proxied 推奨 |

3. SSL/TLS → Overview で **Full**（推奨）  
   証明書エラー時はいったん **Flexible** でも可（学習用の暫定）

数分待つと `https://freshberrymarket.com/` が VPS を向きます。

### 自宅 Tunnel を止める

もう不要なら、Mac で動かしている:

```bash
# Ctrl+C で停止
cloudflared tunnel run freshberrymarket
python app.py
```

を止めてOKです（VPS 側が動いていればサイトは生きたまま）。

## 5. 更新のたびに

VPS 上で:

```bash
cd /var/www/freshberrymarket
sudo bash deploy/vps/deploy.sh
```

## 6. よく使うコマンド

```bash
sudo systemctl status freshberrymarket
sudo journalctl -u freshberrymarket -f
sudo nginx -t && sudo systemctl reload nginx
```

## 注意

- SQLite / `uploads` は VPS ディスクに保存されます（再デプロイで消えにくい）
- バックアップは `products.db` と `uploads/` を定期コピーすると安心です
- 本番 Stripe（`sk_live_`）はこの学習用設定のままでは使えません
