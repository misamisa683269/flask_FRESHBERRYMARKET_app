# FRESHBERRYMARKET（Farm to Palm）

ブルーベリー関連商品の **簡易 EC アプリ**です。  
**Flask + SQLite** で動く、学習・ポートフォリオ向けの最小構成です。

商品閲覧からカート・注文・管理まで一通り体験できます。  
決済は **Stripe テスト（Checkout）** に対応しています。本番デプロイ設定は含みません。

## 必要なもの

- Python 3
- ターミナル（macOS なら Terminal / Cursor のターミナル）

## セットアップと起動

```bash
cd ~/camp/python/blueberry_app/flask_FRESHBERRYMARKET_app

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
python app.py
```

ブラウザで http://127.0.0.1:8000/ を開きます。終了は `Ctrl + C` です。

`.env` の `SECRET_KEY` は、できるだけ長いランダムな文字列に書き換えてください。  
`.env` は Git 管理外です（コミットしないでください）。

## 初期アカウント

起動時に管理者がいない場合、次が自動作成されます。

| 種類 | ユーザー名 | パスワード | できること |
|------|------------|------------|------------|
| 管理者 | `admin` | `admin123` | 商品管理・注文管理・お問い合わせ一覧・管理者追加など |
| 一般 | `/register` で作成 | （任意・8文字以上） | 購入・カート・注文・お気に入り・レビューなど |

追加の管理者は、既存管理者が `/admin/users/new` から作成できます。  
ログイン後は `/account` で自分のユーザー名を変更できます。

## 主な機能

- 商品一覧・詳細・キーワード検索
- 商品の追加・編集・削除・画像アップロード（管理者）
- 在庫管理（カート追加・注文時にチェック、キャンセル時に戻す）
- カート（数量変更・削除・空にする）
- お気に入り
- 注文（配送先・送料・Stripeテスト決済・確認メール開発用・キャンセル／返品ステータス）
- レビュー（評価・コメント）
- お問い合わせ（DB 保存＋開発時はターミナル表示）
- ユーザー登録・ログイン・ログアウト（一般 / 管理者）
- アカウント設定（ユーザー名変更）
- 管理者アカウント追加（既存管理者のみ）
- CSRF 対策、`SECRET_KEY` の環境変数読み込み
- フラッシュメッセージ

## 主な URL

| URL | 内容 |
|-----|------|
| `/` | トップ |
| `/products` | 商品一覧（`?q=` で検索） |
| `/products/<id>` | 商品詳細 |
| `/cart` | カート |
| `/checkout` | 注文手続き |
| `/orders` | 自分の注文 |
| `/favorites` | お気に入り（ログイン必要） |
| `/contact` | お問い合わせ |
| `/account` | アカウント設定（ユーザー名変更・ログイン必要） |
| `/login` / `/register` | ログイン / 新規登録 |
| `/products/new` | 商品追加（管理者） |
| `/admin/orders` | 注文管理（管理者） |
| `/admin/contacts` | お問い合わせ一覧（管理者） |
| `/admin/users/new` | 管理者アカウント追加（管理者） |

## 送料・注文ステータス

**送料:** 基本 500円 ／ 商品小計 5,000円以上で無料

| ステータス | 意味 |
|------------|------|
| 受付 | 注文直後。お客様からキャンセル可（在庫が戻る） |
| 準備中 / 発送済み | お客様からのキャンセル不可 |
| キャンセル | キャンセル済み（在庫戻し済み） |
| 返品受付 | 返品対応中（在庫はまだ戻さない） |
| 返品完了 | 返品完了（在庫を戻す） |

在庫戻しは「キャンセル」「返品完了」への変更時に **1回だけ** 行われます。

## 注文確認メール（開発用）

注文完了時、起動中のターミナルに宛先・件名・本文が出力されます。  
`.env` の `MAIL_SUPPRESS_SEND=true`（初期値）のときは実送信しません。

## Stripe テスト決済

1. [Stripe Dashboard](https://dashboard.stripe.com/) のテストモードで API キーを取得
2. `.env` に貼る（**コミットしない**）

```bash
STRIPE_SECRET_KEY=sk_test_xxxxxxxx
STRIPE_PUBLISHABLE_KEY=pk_test_xxxxxxxx
```

3. アプリを再起動 → カート → 注文手続き →「お支払いに進む（Stripe）」
4. テストカード: `4242 4242 4242 4242` / 将来の日付 / CVC 任意

※ 本番キー（`sk_live_`）は使わないでください。

## プロジェクト構成（抜粋）

```text
flask_FRESHBERRYMARKET_app/
├── app.py              # Flask アプリ本体
├── requirements.txt
├── .env.example        # 環境変数の見本
├── .gitignore
├── README.md
├── templates/
├── static/
├── uploads/            # 画像（Git 管理外）
└── products.db         # SQLite（起動時作成・Git 管理外）
```

## 補足

- 初回起動時に DB と初期商品が作られます
- `.gitignore` 対象: `.venv` / `*.db` / `uploads/` / `.env`
- 学習用の簡易アプリです（本番向けのデプロイ設定は含みません。決済はテストモードのみ）
