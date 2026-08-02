import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import os
import stripe

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "freshberrymarket-dev-secret")
csrf = CSRFProtect(app)


@app.template_filter("yen")
def yen_filter(value):
    """金額表示用。1200 → '1,200'（円はテンプレート側で付ける）"""
    if value is None:
        return "0"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


DATABASE = BASE_DIR / "products.db"
UPLOAD_DIR = BASE_DIR / "uploads"
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ORDER_STATUSES = ("受付", "準備中", "発送済み", "キャンセル", "返品受付", "返品完了")
STOCK_RESTORE_STATUSES = frozenset({"キャンセル", "返品完了"})
SHIPPING_FEE = 500
FREE_SHIPPING_THRESHOLD = 5000
MIN_PASSWORD_LENGTH = 8
PASSWORD_RESET_HOURS = 1

SEED_PRODUCTS = [
    (
        "ブルーベリー 500g",
        1200,
        "収穫したての生ブルーベリー。そのまま食べてもおいしいです。",
        10,
    ),
    (
        "ブルーベリー 1kg",
        2200,
        "たっぷり1kg。冷凍保存にもおすすめです。",
        10,
    ),
    (
        "ジャムセット",
        1800,
        "自家製ブルーベリージャムの詰め合わせです。",
        10,
    ),
]


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    UPLOAD_DIR.mkdir(exist_ok=True)
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            description TEXT NOT NULL,
            image_filename TEXT,
            stock INTEGER NOT NULL DEFAULT 10
        )
        """
    )
    product_columns = [
        row[1] for row in conn.execute("PRAGMA table_info(products)").fetchall()
    ]
    if "image_filename" not in product_columns:
        conn.execute("ALTER TABLE products ADD COLUMN image_filename TEXT")
    if "stock" not in product_columns:
        conn.execute("ALTER TABLE products ADD COLUMN stock INTEGER")
        conn.execute("UPDATE products SET stock = 10 WHERE stock IS NULL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
        )
        """
    )
    user_columns = [
        row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()
    ]
    if "role" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT")
        conn.execute("UPDATE users SET role = 'user' WHERE role IS NULL")
    if "email" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email
        ON users (email)
        WHERE email IS NOT NULL AND email != ''
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            user_id INTEGER,
            recipient_name TEXT,
            postal_code TEXT,
            address TEXT,
            phone TEXT,
            status TEXT NOT NULL DEFAULT '受付',
            subtotal INTEGER,
            shipping_fee INTEGER,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    order_columns = [
        row[1] for row in conn.execute("PRAGMA table_info(orders)").fetchall()
    ]
    if "user_id" not in order_columns:
        conn.execute("ALTER TABLE orders ADD COLUMN user_id INTEGER")
    for column in ("recipient_name", "postal_code", "address", "phone", "email", "stripe_session_id"):
        if column not in order_columns:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {column} TEXT")
    if "status" not in order_columns:
        conn.execute("ALTER TABLE orders ADD COLUMN status TEXT")
        conn.execute("UPDATE orders SET status = '受付' WHERE status IS NULL")
    if "subtotal" not in order_columns:
        conn.execute("ALTER TABLE orders ADD COLUMN subtotal INTEGER")
    if "shipping_fee" not in order_columns:
        conn.execute("ALTER TABLE orders ADD COLUMN shipping_fee INTEGER")
        conn.execute(
            "UPDATE orders SET shipping_fee = 0 WHERE shipping_fee IS NULL"
        )
        conn.execute(
            """
            UPDATE orders
            SET subtotal = total
            WHERE subtotal IS NULL
            """
        )
    if "stock_restored" not in order_columns:
        conn.execute("ALTER TABLE orders ADD COLUMN stock_restored INTEGER")
        conn.execute(
            "UPDATE orders SET stock_restored = 0 WHERE stock_restored IS NULL"
        )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            subtotal INTEGER NOT NULL,
            product_id INTEGER,
            FOREIGN KEY (order_id) REFERENCES orders (id)
        )
        """
    )
    order_item_columns = [
        row[1] for row in conn.execute("PRAGMA table_info(order_items)").fetchall()
    ]
    if "product_id" not in order_item_columns:
        conn.execute("ALTER TABLE order_items ADD COLUMN product_id INTEGER")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (product_id, user_id),
            FOREIGN KEY (product_id) REFERENCES products (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            user_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (user_id, product_id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
        """
    )
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    if count == 0:
        conn.executemany(
            """
            INSERT INTO products (name, price, description, stock)
            VALUES (?, ?, ?, ?)
            """,
            SEED_PRODUCTS,
        )

    admin_count = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin'"
    ).fetchone()[0]
    if admin_count == 0:
        conn.execute(
            """
            INSERT INTO users (username, password_hash, role, email)
            VALUES (?, ?, ?, ?)
            """,
            (
                "admin",
                generate_password_hash("admin123"),
                "admin",
                "admin@example.com",
            ),
        )

    conn.commit()
    conn.close()


def get_all_products():
    conn = get_db()
    products = conn.execute(
        """
        SELECT id, name, price, description, image_filename, stock
        FROM products
        ORDER BY id
        """
    ).fetchall()
    conn.close()
    return products


def search_products(keyword):
    conn = get_db()
    like = f"%{keyword}%"
    products = conn.execute(
        """
        SELECT id, name, price, description, image_filename, stock
        FROM products
        WHERE name LIKE ? OR description LIKE ?
        ORDER BY id
        """,
        (like, like),
    ).fetchall()
    conn.close()
    return products


def get_product(product_id):
    conn = get_db()
    product = conn.execute(
        """
        SELECT id, name, price, description, image_filename, stock
        FROM products
        WHERE id = ?
        """,
        (product_id,),
    ).fetchone()
    conn.close()
    return product


def save_product_image(file_storage):
    if file_storage is None or not file_storage.filename:
        return None

    original = secure_filename(file_storage.filename)
    if not original:
        return None

    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False

    filename = f"{uuid.uuid4().hex}{ext}"
    file_storage.save(UPLOAD_DIR / filename)
    return filename


def remove_product_image_file(filename):
    if not filename:
        return
    path = UPLOAD_DIR / filename
    if path.is_file():
        path.unlink()


def create_product(name, price, description, stock, image_filename=None):
    conn = get_db()
    cursor = conn.execute(
        """
        INSERT INTO products (name, price, description, image_filename, stock)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, price, description, image_filename, stock),
    )
    conn.commit()
    product_id = cursor.lastrowid
    conn.close()
    return product_id


def update_product(product_id, name, price, description, stock, image_filename=None):
    conn = get_db()
    if image_filename is None:
        conn.execute(
            """
            UPDATE products
            SET name = ?, price = ?, description = ?, stock = ?
            WHERE id = ?
            """,
            (name, price, description, stock, product_id),
        )
    else:
        conn.execute(
            """
            UPDATE products
            SET name = ?, price = ?, description = ?, image_filename = ?, stock = ?
            WHERE id = ?
            """,
            (name, price, description, image_filename, stock, product_id),
        )
    conn.commit()
    conn.close()


def delete_product(product_id):
    product = get_product(product_id)
    conn = get_db()
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    if product is not None:
        remove_product_image_file(product["image_filename"])


def is_valid_email(email):
    email = (email or "").strip()
    return "@" in email and "." in email.split("@")[-1]


def create_user(username, password, email, role="user"):
    conn = get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO users (username, password_hash, role, email)
            VALUES (?, ?, ?, ?)
            """,
            (username, generate_password_hash(password), role, email),
        )
        conn.commit()
        user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        return None
    conn.close()
    return user_id


def get_user_by_username(username):
    conn = get_db()
    user = conn.execute(
        """
        SELECT id, username, password_hash, role, email
        FROM users
        WHERE username = ?
        """,
        (username,),
    ).fetchone()
    conn.close()
    return user


def get_user_by_email(email):
    conn = get_db()
    user = conn.execute(
        """
        SELECT id, username, password_hash, role, email
        FROM users
        WHERE lower(email) = lower(?)
        """,
        (email,),
    ).fetchone()
    conn.close()
    return user


def get_user_by_username_or_email(identifier):
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    user = get_user_by_username(identifier)
    if user is not None:
        return user
    if "@" in identifier:
        return get_user_by_email(identifier)
    return None


def update_account(user_id, new_username, new_email):
    """ユーザー名とメールを更新。(成功したか, エラーメッセージ) を返す。"""
    existing_name = get_user_by_username(new_username)
    if existing_name is not None and existing_name["id"] != user_id:
        return False, "そのユーザー名はすでに使われています。"
    existing_email = get_user_by_email(new_email)
    if existing_email is not None and existing_email["id"] != user_id:
        return False, "そのメールアドレスはすでに使われています。"

    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET username = ?, email = ? WHERE id = ?",
            (new_username, new_email, user_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False, "そのユーザー名またはメールアドレスはすでに使われています。"
    conn.close()
    return True, None


def update_password(user_id, new_password):
    conn = get_db()
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), user_id),
    )
    conn.commit()
    conn.close()


def create_password_reset_token(user_id):
    token = secrets.token_urlsafe(32)
    expires_at = (
        datetime.now() + timedelta(hours=PASSWORD_RESET_HOURS)
    ).isoformat(timespec="seconds")
    conn = get_db()
    conn.execute(
        """
        UPDATE password_reset_tokens
        SET used = 1
        WHERE user_id = ? AND used = 0
        """,
        (user_id,),
    )
    conn.execute(
        """
        INSERT INTO password_reset_tokens (token, user_id, expires_at, used)
        VALUES (?, ?, ?, 0)
        """,
        (token, user_id, expires_at),
    )
    conn.commit()
    conn.close()
    return token


def get_password_reset_token(token):
    conn = get_db()
    row = conn.execute(
        """
        SELECT id, token, user_id, expires_at, used
        FROM password_reset_tokens
        WHERE token = ?
        """,
        (token,),
    ).fetchone()
    conn.close()
    return row


def mark_password_reset_token_used(token_id):
    conn = get_db()
    conn.execute(
        "UPDATE password_reset_tokens SET used = 1 WHERE id = ?",
        (token_id,),
    )
    conn.commit()
    conn.close()


def send_password_reset_notice(to_email, reset_url, username):
    """開発中はコンソール出力。MAIL_SUPPRESS_SEND=true なら実送信しない。"""
    subject = "【FRESHBERRYMARKET】パスワード再設定のご案内"
    body = (
        f"{username} さん\n\n"
        "パスワード再設定のリクエストを受け付けました。\n"
        "次のURLから、1時間以内に新しいパスワードを設定してください。\n\n"
        f"{reset_url}\n\n"
        "心当たりがない場合は、このメッセージを無視してください。"
    )
    print("\n===== Password reset email =====")
    print(f"To: {to_email or '(メール未登録・コンソール確認用)'}")
    print(f"Subject: {subject}")
    print("Body:")
    print(body)
    print("===== End of email =====\n")

    suppress = os.environ.get("MAIL_SUPPRESS_SEND", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if suppress:
        print("(MAIL_SUPPRESS_SEND=true — SMTP送信は行いません。上のURLで再設定できます)")
    return True


def get_admin_users():
    conn = get_db()
    users = conn.execute(
        """
        SELECT id, username, email
        FROM users
        WHERE role = 'admin'
        ORDER BY id
        """
    ).fetchall()
    conn.close()
    return users


def get_user_by_id(user_id):
    conn = get_db()
    user = conn.execute(
        """
        SELECT id, username, password_hash, role, email
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()
    conn.close()
    return user


def delete_admin_user(target_user_id, acting_user_id):
    """管理者を削除する。(成功したか, メッセージ) を返す。"""
    if target_user_id == acting_user_id:
        return False, "自分自身のアカウントは削除できません。"

    target = get_user_by_id(target_user_id)
    if target is None or target["role"] != "admin":
        return False, "削除できる管理者アカウントが見つかりません。"

    admins = get_admin_users()
    if len(admins) <= 1:
        return False, "管理者があと1人のため削除できません。"

    conn = get_db()
    conn.execute(
        "DELETE FROM password_reset_tokens WHERE user_id = ?",
        (target_user_id,),
    )
    conn.execute("DELETE FROM favorites WHERE user_id = ?", (target_user_id,))
    cursor = conn.execute(
        "DELETE FROM users WHERE id = ? AND role = 'admin'",
        (target_user_id,),
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    if not deleted:
        return False, "管理者の削除に失敗しました。"
    return True, f"管理者「{target['username']}」を削除しました。"


def build_order_confirmation_email(order_id, items, subtotal, shipping_fee, total, shipping):
    lines = [
        "FRESHBERRYMARKET をご利用いただきありがとうございます。",
        "",
        f"注文番号: {order_id}",
        "",
        "【ご注文内容】",
    ]
    for item in items:
        lines.append(
            f"- {item['name']} : {item['price']}円 × {item['quantity']} = {item['subtotal']}円"
        )
    lines.extend(
        [
            "",
            f"小計: {subtotal}円",
            f"送料: {'無料' if shipping_fee == 0 else f'{shipping_fee}円'}",
            f"合計: {total}円",
            "",
            "【配送先】",
            f"氏名: {shipping['recipient_name']}",
            f"郵便番号: {shipping['postal_code']}",
            f"住所: {shipping['address']}",
            f"電話番号: {shipping['phone']}",
            "",
            "※このメールは注文確認用です。",
        ]
    )
    subject = f"【FRESHBERRYMARKET】ご注文ありがとうございます（注文番号: {order_id}）"
    return subject, "\n".join(lines)


def send_order_confirmation_email(to_email, subject, body):
    """開発中はコンソール出力。MAIL_SUPPRESS_SEND=true なら実送信しない。"""
    print("\n===== Order confirmation email =====")
    print(f"To: {to_email}")
    print(f"Subject: {subject}")
    print("Body:")
    print(body)
    print("===== End of email =====\n")

    suppress = os.environ.get("MAIL_SUPPRESS_SEND", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if suppress:
        print("(MAIL_SUPPRESS_SEND=true — SMTP送信は行いません)")
        return True

    # 将来の実送信用（MAIL_SERVER 未設定なら送信せず終了）
    mail_server = os.environ.get("MAIL_SERVER", "").strip()
    if not mail_server:
        print("(MAIL_SERVER 未設定のため、コンソール出力のみです)")
        return True

    # SMTP は未実装。設定があっても今はコンソールのみ。
    print("(SMTP実送信はまだ未対応です。内容は上記のとおりです)")
    return True


def get_stripe_secret_key():
    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not key or key.startswith("sk_test_your_") or "ここに" in key:
        return None
    if key.startswith("sk_live_"):
        return None
    if not key.startswith("sk_test_"):
        return None
    return key


def create_order(items, subtotal, shipping_fee, total, user_id, shipping, stripe_session_id=None):
    conn = get_db()

    if stripe_session_id:
        existing = conn.execute(
            "SELECT id FROM orders WHERE stripe_session_id = ?",
            (stripe_session_id,),
        ).fetchone()
        if existing is not None:
            conn.close()
            return existing["id"]

    for item in items:
        row = conn.execute(
            "SELECT stock FROM products WHERE id = ?",
            (item["id"],),
        ).fetchone()
        if row is None or row["stock"] is None or row["stock"] < item["quantity"]:
            conn.close()
            return None

    cursor = conn.execute(
        """
        INSERT INTO orders (
            total, created_at, user_id,
            recipient_name, postal_code, address, phone, email, status,
            subtotal, shipping_fee, stock_restored, stripe_session_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            total,
            datetime.now().isoformat(timespec="seconds"),
            user_id,
            shipping["recipient_name"],
            shipping["postal_code"],
            shipping["address"],
            shipping["phone"],
            shipping["email"],
            "受付",
            subtotal,
            shipping_fee,
            0,
            stripe_session_id,
        ),
    )
    order_id = cursor.lastrowid
    conn.executemany(
        """
        INSERT INTO order_items (order_id, name, price, quantity, subtotal, product_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                order_id,
                item["name"],
                item["price"],
                item["quantity"],
                item["subtotal"],
                item["id"],
            )
            for item in items
        ],
    )
    for item in items:
        conn.execute(
            "UPDATE products SET stock = stock - ? WHERE id = ?",
            (item["quantity"], item["id"]),
        )
    conn.commit()
    conn.close()
    return order_id


def get_order_by_stripe_session_id(stripe_session_id):
    conn = get_db()
    order = conn.execute(
        """
        SELECT id, total, created_at, user_id,
               recipient_name, postal_code, address, phone, email, status,
               subtotal, shipping_fee, stock_restored, stripe_session_id
        FROM orders
        WHERE stripe_session_id = ?
        """,
        (stripe_session_id,),
    ).fetchone()
    conn.close()
    return order


def restore_order_stock(conn, order_id):
    """在庫を戻す。成功したら True。すでに戻済みなら False。"""
    order = conn.execute(
        "SELECT stock_restored FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    if order is None:
        return False
    if order["stock_restored"]:
        return False

    items = conn.execute(
        """
        SELECT name, quantity, product_id
        FROM order_items
        WHERE order_id = ?
        """,
        (order_id,),
    ).fetchall()
    for item in items:
        if item["product_id"] is not None:
            conn.execute(
                "UPDATE products SET stock = stock + ? WHERE id = ?",
                (item["quantity"], item["product_id"]),
            )
        else:
            conn.execute(
                """
                UPDATE products
                SET stock = stock + ?
                WHERE id = (
                    SELECT id FROM products WHERE name = ? ORDER BY id LIMIT 1
                )
                """,
                (item["quantity"], item["name"]),
            )
    conn.execute(
        "UPDATE orders SET stock_restored = 1 WHERE id = ?",
        (order_id,),
    )
    return True


def get_order(order_id):
    conn = get_db()
    order = conn.execute(
        """
        SELECT id, total, created_at, user_id,
               recipient_name, postal_code, address, phone, email, status,
               subtotal, shipping_fee, stock_restored
        FROM orders
        WHERE id = ?
        """,
        (order_id,),
    ).fetchone()
    conn.close()
    return order


def get_order_items(order_id):
    conn = get_db()
    items = conn.execute(
        """
        SELECT name, price, quantity, subtotal, product_id
        FROM order_items
        WHERE order_id = ?
        ORDER BY id
        """,
        (order_id,),
    ).fetchall()
    conn.close()
    return items


def get_orders_for_user(user_id):
    conn = get_db()
    orders = conn.execute(
        """
        SELECT id, total, created_at, user_id,
               recipient_name, postal_code, address, phone, email, status,
               subtotal, shipping_fee, stock_restored
        FROM orders
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user_id,),
    ).fetchall()
    result = []
    for order in orders:
        items = conn.execute(
            """
            SELECT name, price, quantity, subtotal, product_id
            FROM order_items
            WHERE order_id = ?
            ORDER BY id
            """,
            (order["id"],),
        ).fetchall()
        result.append({"order": order, "order_items": items})
    conn.close()
    return result


def get_all_orders():
    conn = get_db()
    orders = conn.execute(
        """
        SELECT id, total, created_at, user_id,
               recipient_name, postal_code, address, phone, email, status,
               subtotal, shipping_fee, stock_restored
        FROM orders
        ORDER BY id DESC
        """
    ).fetchall()
    result = []
    for order in orders:
        items = conn.execute(
            """
            SELECT name, price, quantity, subtotal, product_id
            FROM order_items
            WHERE order_id = ?
            ORDER BY id
            """,
            (order["id"],),
        ).fetchall()
        result.append({"order": order, "order_items": items})
    conn.close()
    return result


def update_order_status(order_id, status):
    if status not in ORDER_STATUSES:
        return False
    conn = get_db()
    order = conn.execute(
        "SELECT id, status FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    if order is None:
        conn.close()
        return False

    conn.execute(
        "UPDATE orders SET status = ? WHERE id = ?",
        (status, order_id),
    )
    if status in STOCK_RESTORE_STATUSES:
        restore_order_stock(conn, order_id)
    conn.commit()
    conn.close()
    return True


def cancel_order_by_user(order_id, user_id):
    """受付の自分の注文のみキャンセル。成功メッセージ用に True/エラー理由。"""
    conn = get_db()
    order = conn.execute(
        """
        SELECT id, user_id, status
        FROM orders
        WHERE id = ?
        """,
        (order_id,),
    ).fetchone()
    if order is None:
        conn.close()
        return False, "注文が見つかりません。"
    if order["user_id"] != user_id:
        conn.close()
        return False, "この注文はキャンセルできません。"
    if (order["status"] or "受付") != "受付":
        conn.close()
        return False, "「受付」の注文のみキャンセルできます（準備中・発送済みは不可）。"

    conn.execute(
        "UPDATE orders SET status = ? WHERE id = ?",
        ("キャンセル", order_id),
    )
    restore_order_stock(conn, order_id)
    conn.commit()
    conn.close()
    return True, None


def get_reviews_for_product(product_id):
    conn = get_db()
    reviews = conn.execute(
        """
        SELECT reviews.id, reviews.rating, reviews.comment, reviews.created_at,
               users.username
        FROM reviews
        JOIN users ON users.id = reviews.user_id
        WHERE reviews.product_id = ?
        ORDER BY reviews.id DESC
        """,
        (product_id,),
    ).fetchall()
    conn.close()
    return reviews


def get_user_review(product_id, user_id):
    conn = get_db()
    review = conn.execute(
        """
        SELECT id, rating, comment, created_at
        FROM reviews
        WHERE product_id = ? AND user_id = ?
        """,
        (product_id, user_id),
    ).fetchone()
    conn.close()
    return review


def save_review(product_id, user_id, rating, comment):
    conn = get_db()
    existing = conn.execute(
        """
        SELECT id FROM reviews
        WHERE product_id = ? AND user_id = ?
        """,
        (product_id, user_id),
    ).fetchone()
    now = datetime.now().isoformat(timespec="seconds")
    if existing:
        conn.execute(
            """
            UPDATE reviews
            SET rating = ?, comment = ?, created_at = ?
            WHERE id = ?
            """,
            (rating, comment, now, existing["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO reviews (product_id, user_id, rating, comment, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (product_id, user_id, rating, comment, now),
        )
    conn.commit()
    conn.close()


def save_contact(name, email, message, user_id=None):
    conn = get_db()
    cursor = conn.execute(
        """
        INSERT INTO contacts (name, email, message, created_at, user_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            name,
            email,
            message,
            datetime.now().isoformat(timespec="seconds"),
            user_id,
        ),
    )
    conn.commit()
    contact_id = cursor.lastrowid
    conn.close()
    return contact_id


def get_all_contacts():
    conn = get_db()
    contacts = conn.execute(
        """
        SELECT contacts.id, contacts.name, contacts.email, contacts.message,
               contacts.created_at, contacts.user_id, users.username
        FROM contacts
        LEFT JOIN users ON users.id = contacts.user_id
        ORDER BY contacts.id DESC
        """
    ).fetchall()
    conn.close()
    return contacts


def print_contact_message(contact_id, name, email, message):
    print("\n===== Contact form message =====")
    print(f"ID: {contact_id}")
    print(f"Name: {name}")
    print(f"Email: {email}")
    print("Message:")
    print(message)
    print("===== End of contact =====\n")


def is_favorite(user_id, product_id):
    if user_id is None:
        return False
    conn = get_db()
    row = conn.execute(
        """
        SELECT id FROM favorites
        WHERE user_id = ? AND product_id = ?
        """,
        (user_id, product_id),
    ).fetchone()
    conn.close()
    return row is not None


def get_favorite_product_ids(user_id):
    if user_id is None:
        return set()
    conn = get_db()
    rows = conn.execute(
        "SELECT product_id FROM favorites WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    conn.close()
    return {row["product_id"] for row in rows}


def add_favorite(user_id, product_id):
    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO favorites (user_id, product_id, created_at)
            VALUES (?, ?, ?)
            """,
            (user_id, product_id, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
    finally:
        conn.close()


def remove_favorite(user_id, product_id):
    conn = get_db()
    conn.execute(
        "DELETE FROM favorites WHERE user_id = ? AND product_id = ?",
        (user_id, product_id),
    )
    conn.commit()
    conn.close()


def get_favorites_for_user(user_id):
    conn = get_db()
    products = conn.execute(
        """
        SELECT products.id, products.name, products.price, products.description,
               products.image_filename, products.stock, favorites.created_at
        FROM favorites
        JOIN products ON products.id = favorites.product_id
        WHERE favorites.user_id = ?
        ORDER BY favorites.id DESC
        """,
        (user_id,),
    ).fetchall()
    conn.close()
    return products


def build_cart_items():
    cart_data = session.get("cart", {})
    items = []
    subtotal = 0

    for product_id, quantity in cart_data.items():
        product = get_product(int(product_id))
        if product is None:
            continue
        item_subtotal = product["price"] * quantity
        subtotal += item_subtotal
        items.append(
            {
                "id": product["id"],
                "name": product["name"],
                "price": product["price"],
                "quantity": quantity,
                "subtotal": item_subtotal,
                "stock": product["stock"] if product["stock"] is not None else 0,
            }
        )

    return items, subtotal


def calc_shipping_fee(subtotal):
    if subtotal <= 0:
        return 0
    if subtotal >= FREE_SHIPPING_THRESHOLD:
        return 0
    return SHIPPING_FEE


def cart_summary():
    items, subtotal = build_cart_items()
    shipping_fee = calc_shipping_fee(subtotal)
    total = subtotal + shipping_fee
    return items, subtotal, shipping_fee, total


def current_user_id():
    return session.get("user_id")


def is_admin():
    return session.get("role") == "admin"


def require_admin():
    if current_user_id() is None:
        flash("ログインが必要です。", "error")
        return redirect(url_for("login"))
    if not is_admin():
        flash("管理者のみ操作できます。", "error")
        return redirect(url_for("products"))
    return None


@app.context_processor
def inject_auth():
    return {
        "current_username": session.get("username"),
        "is_logged_in": current_user_id() is not None,
        "is_admin": is_admin(),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        if not username or not email or not password:
            error = "ユーザー名・メールアドレス・パスワードを入力してください。"
        elif not is_valid_email(email):
            error = "メールアドレスの形式が正しくありません。"
        elif len(password) < MIN_PASSWORD_LENGTH:
            error = f"パスワードは{MIN_PASSWORD_LENGTH}文字以上にしてください。"
        else:
            user_id = create_user(username, password, email)
            if user_id is None:
                if get_user_by_username(username) is not None:
                    error = "そのユーザー名はすでに使われています。"
                else:
                    error = "そのメールアドレスはすでに使われています。"
            else:
                session["user_id"] = user_id
                session["username"] = username
                session["role"] = "user"
                flash("新規登録が完了しました。", "success")
                return redirect(url_for("index"))
    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_user_by_username(username)
        if user is None or not check_password_hash(user["password_hash"], password):
            error = "ユーザー名またはパスワードが違います。"
        else:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"] if user["role"] else "user"
            flash("ログインしました。", "success")
            return redirect(url_for("index"))
    return render_template("login.html", error=error)


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        user = get_user_by_username_or_email(identifier) if identifier else None
        if user is not None:
            token = create_password_reset_token(user["id"])
            reset_url = url_for("reset_password", token=token, _external=True)
            send_password_reset_notice(user["email"], reset_url, user["username"])
        flash(
            "入力内容が登録されている場合、パスワード再設定のご案内を送りました。"
            "開発中はサーバーのターミナルに再設定URLが表示されます。",
            "success",
        )
        return redirect(url_for("login"))
    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    row = get_password_reset_token(token)
    now = datetime.now().isoformat(timespec="seconds")
    if (
        row is None
        or row["used"]
        or row["expires_at"] < now
    ):
        flash("再設定リンクが無効か、有効期限切れです。もう一度お試しください。", "error")
        return redirect(url_for("forgot_password"))

    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        if len(password) < MIN_PASSWORD_LENGTH:
            error = f"パスワードは{MIN_PASSWORD_LENGTH}文字以上にしてください。"
        elif password != password_confirm:
            error = "パスワード（確認）が一致しません。"
        else:
            update_password(row["user_id"], password)
            mark_password_reset_token_used(row["id"])
            flash("パスワードを再設定しました。ログインしてください。", "success")
            return redirect(url_for("login"))

    return render_template("reset_password.html", error=error, token=token)


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("username", None)
    session.pop("role", None)
    flash("ログアウトしました。", "success")
    return redirect(url_for("index"))


@app.route("/account", methods=["GET", "POST"])
def account():
    user_id = current_user_id()
    if user_id is None:
        flash("ログインが必要です。", "error")
        return redirect(url_for("login"))

    user = get_user_by_id(user_id)
    if user is None:
        flash("ユーザーが見つかりません。", "error")
        return redirect(url_for("login"))

    error = None
    if request.method == "POST":
        new_username = request.form.get("username", "").strip()
        new_email = request.form.get("email", "").strip()
        if not new_username or not new_email:
            error = "ユーザー名とメールアドレスを入力してください。"
        elif not is_valid_email(new_email):
            error = "メールアドレスの形式が正しくありません。"
        else:
            ok, message = update_account(user_id, new_username, new_email)
            if ok:
                session["username"] = new_username
                flash("アカウント情報を更新しました。", "success")
                return redirect(url_for("account"))
            error = message

    return render_template(
        "account.html",
        error=error,
        username=user["username"],
        email=user["email"] or "",
    )


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/products")
def products():
    query = request.args.get("q", "").strip()
    if query:
        product_list = search_products(query)
    else:
        product_list = get_all_products()
    favorite_ids = get_favorite_product_ids(current_user_id())
    return render_template(
        "products.html",
        products=product_list,
        q=query,
        favorite_ids=favorite_ids,
    )


@app.route("/products/new", methods=["GET", "POST"])
def product_new():
    blocked = require_admin()
    if blocked is not None:
        return blocked

    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        price = request.form.get("price", type=int)
        description = request.form.get("description", "").strip()
        stock = request.form.get("stock", type=int)
        image_result = save_product_image(request.files.get("image"))

        if (
            not name
            or price is None
            or price < 0
            or not description
            or stock is None
            or stock < 0
        ):
            error = "商品名・価格（0以上）・説明・在庫（0以上）を入力してください。"
        elif image_result is False:
            error = "画像は png / jpg / jpeg / gif / webp のみアップロードできます。"
        else:
            create_product(name, price, description, stock, image_result)
            flash("商品を追加しました。", "success")
            return redirect(url_for("products"))

    return render_template("product_new.html", error=error)


@app.route("/products/<int:product_id>")
def product_detail(product_id):
    product = get_product(product_id)
    if product is None:
        abort(404)

    user_id = current_user_id()
    my_review = get_user_review(product_id, user_id) if user_id else None
    return render_template(
        "product_detail.html",
        product=product,
        reviews=get_reviews_for_product(product_id),
        my_review=my_review,
        is_favorited=is_favorite(user_id, product_id),
    )


@app.route("/products/<int:product_id>/favorite", methods=["POST"])
def product_favorite_toggle(product_id):
    user_id = current_user_id()
    if user_id is None:
        flash("お気に入りにはログインが必要です。", "error")
        return redirect(url_for("login"))

    product = get_product(product_id)
    if product is None:
        abort(404)

    if is_favorite(user_id, product_id):
        remove_favorite(user_id, product_id)
        flash("お気に入りから削除しました。", "success")
    else:
        add_favorite(user_id, product_id)
        flash("お気に入りに追加しました。", "success")

    next_url = request.form.get("next", "").strip()
    if next_url in ("products", "favorites", "detail"):
        if next_url == "products":
            return redirect(url_for("products"))
        if next_url == "favorites":
            return redirect(url_for("favorites"))
    return redirect(url_for("product_detail", product_id=product_id))


@app.route("/favorites")
def favorites():
    user_id = current_user_id()
    if user_id is None:
        flash("お気に入り一覧を見るにはログインが必要です。", "error")
        return redirect(url_for("login"))

    return render_template(
        "favorites.html",
        products=get_favorites_for_user(user_id),
    )


@app.route("/products/<int:product_id>/reviews", methods=["POST"])
def product_review(product_id):
    user_id = current_user_id()
    if user_id is None:
        flash("レビュー投稿にはログインが必要です。", "error")
        return redirect(url_for("login"))

    product = get_product(product_id)
    if product is None:
        abort(404)

    rating = request.form.get("rating", type=int)
    comment = request.form.get("comment", "").strip()

    if rating is None or rating < 1 or rating > 5 or not comment:
        flash("評価（1〜5）とコメントを入力してください。", "error")
        return redirect(url_for("product_detail", product_id=product_id))

    save_review(product_id, user_id, rating, comment)
    flash("レビューを保存しました。", "success")
    return redirect(url_for("product_detail", product_id=product_id))


@app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
def product_edit(product_id):
    blocked = require_admin()
    if blocked is not None:
        return blocked

    product = get_product(product_id)
    if product is None:
        abort(404)

    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        price = request.form.get("price", type=int)
        description = request.form.get("description", "").strip()
        stock = request.form.get("stock", type=int)
        image_result = save_product_image(request.files.get("image"))

        if (
            not name
            or price is None
            or price < 0
            or not description
            or stock is None
            or stock < 0
        ):
            error = "商品名・価格（0以上）・説明・在庫（0以上）を入力してください。"
        elif image_result is False:
            error = "画像は png / jpg / jpeg / gif / webp のみアップロードできます。"
        else:
            if image_result:
                remove_product_image_file(product["image_filename"])
                update_product(
                    product_id, name, price, description, stock, image_result
                )
            else:
                update_product(product_id, name, price, description, stock)
            flash("商品を更新しました。", "success")
            return redirect(url_for("product_detail", product_id=product_id))

    return render_template("product_edit.html", product=product, error=error)


@app.route("/products/<int:product_id>/delete", methods=["POST"])
def product_delete(product_id):
    blocked = require_admin()
    if blocked is not None:
        return blocked

    product = get_product(product_id)
    if product is None:
        abort(404)

    delete_product(product_id)

    cart = session.get("cart", {})
    cart.pop(str(product_id), None)
    session["cart"] = cart

    flash("商品を削除しました。", "success")
    return redirect(url_for("products"))


@app.route("/cart/add/<int:product_id>", methods=["POST"])
def cart_add(product_id):
    product = get_product(product_id)
    if product is None:
        abort(404)

    stock = product["stock"] if product["stock"] is not None else 0
    quantity = request.form.get("quantity", type=int)
    if quantity is None or quantity < 1:
        quantity = 1

    cart = session.get("cart", {})
    key = str(product_id)
    new_quantity = cart.get(key, 0) + quantity

    if stock < 1:
        flash("この商品は売り切れです。", "error")
        return redirect(url_for("product_detail", product_id=product_id))

    if new_quantity > stock:
        flash(f"在庫が足りません（在庫: {stock}）。", "error")
        return redirect(url_for("product_detail", product_id=product_id))

    cart[key] = new_quantity
    session["cart"] = cart

    flash(f"カートに {quantity} 個追加しました。", "success")
    return redirect(url_for("cart"))


@app.route("/cart")
def cart():
    items, subtotal, shipping_fee, total = cart_summary()
    return render_template(
        "cart.html",
        items=items,
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        total=total,
        free_shipping_threshold=FREE_SHIPPING_THRESHOLD,
    )


@app.route("/cart/update/<int:product_id>", methods=["POST"])
def cart_update(product_id):
    product = get_product(product_id)
    if product is None:
        abort(404)

    stock = product["stock"] if product["stock"] is not None else 0
    quantity = request.form.get("quantity", type=int)
    cart = session.get("cart", {})
    key = str(product_id)

    if quantity is None or quantity < 1:
        cart.pop(key, None)
        flash("カートから商品を削除しました。", "success")
    elif quantity > stock:
        flash(f"在庫が足りません（在庫: {stock}）。", "error")
    else:
        cart[key] = quantity
        flash("数量を更新しました。", "success")

    session["cart"] = cart
    return redirect(url_for("cart"))


@app.route("/cart/remove/<int:product_id>", methods=["POST"])
def cart_remove(product_id):
    cart = session.get("cart", {})
    cart.pop(str(product_id), None)
    session["cart"] = cart
    flash("カートから商品を削除しました。", "success")
    return redirect(url_for("cart"))


@app.route("/cart/clear", methods=["POST"])
def cart_clear():
    session.pop("cart", None)
    flash("カートを空にしました。", "success")
    return redirect(url_for("cart"))


@app.route("/checkout", methods=["GET"])
def checkout():
    if current_user_id() is None:
        flash("注文するにはログインが必要です。", "error")
        return redirect(url_for("login"))

    items, subtotal, shipping_fee, total = cart_summary()
    if not items:
        flash("カートが空です。", "error")
        return redirect(url_for("cart"))

    return render_template(
        "checkout.html",
        items=items,
        subtotal=subtotal,
        shipping_fee=shipping_fee,
        total=total,
        free_shipping_threshold=FREE_SHIPPING_THRESHOLD,
        error=None,
    )


@app.route("/order", methods=["POST"])
def order():
    user_id = current_user_id()
    if user_id is None:
        flash("注文するにはログインが必要です。", "error")
        return redirect(url_for("login"))

    items, subtotal, shipping_fee, total = cart_summary()
    if not items:
        flash("カートが空です。", "error")
        return redirect(url_for("cart"))

    shipping = {
        "recipient_name": request.form.get("recipient_name", "").strip(),
        "postal_code": request.form.get("postal_code", "").strip(),
        "address": request.form.get("address", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "email": request.form.get("email", "").strip(),
    }

    if not all(shipping.values()):
        return render_template(
            "checkout.html",
            items=items,
            subtotal=subtotal,
            shipping_fee=shipping_fee,
            total=total,
            free_shipping_threshold=FREE_SHIPPING_THRESHOLD,
            error="氏名・郵便番号・住所・電話番号・メールアドレスをすべて入力してください。",
        )

    for item in items:
        product = get_product(item["id"])
        stock = (
            product["stock"] if product is not None and product["stock"] is not None else 0
        )
        if product is None or stock < item["quantity"]:
            flash("在庫が足りない商品があるため、決済に進めません。", "error")
            return redirect(url_for("cart"))

    stripe_key = get_stripe_secret_key()
    if stripe_key is None:
        flash(
            "Stripe のテスト用シークレットキー（sk_test_...）が .env に設定されていません。",
            "error",
        )
        return redirect(url_for("checkout"))

    stripe.api_key = stripe_key
    session["pending_shipping"] = shipping
    session["pending_total"] = total

    try:
        checkout_session = stripe.checkout.Session.create(
            mode="payment",
            customer_email=shipping["email"],
            line_items=[
                {
                    "price_data": {
                        "currency": "jpy",
                        "unit_amount": total,
                        "product_data": {
                            "name": "FRESHBERRYMARKET ご注文",
                            "description": f"商品小計 {subtotal}円 + 送料 {shipping_fee}円",
                        },
                    },
                    "quantity": 1,
                }
            ],
            success_url=url_for("order_success", _external=True)
            + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=url_for("payment_cancel", _external=True),
        )
    except Exception as exc:
        flash(f"Stripe 決済ページの作成に失敗しました: {exc}", "error")
        return redirect(url_for("checkout"))

    return redirect(checkout_session.url, code=303)


@app.route("/order/success")
def order_success():
    user_id = current_user_id()
    if user_id is None:
        flash("ログインが必要です。", "error")
        return redirect(url_for("login"))

    stripe_session_id = request.args.get("session_id", "").strip()
    if not stripe_session_id:
        flash("決済情報が見つかりません。", "error")
        return redirect(url_for("cart"))

    existing = get_order_by_stripe_session_id(stripe_session_id)
    if existing is not None:
        session["last_order_id"] = existing["id"]
        flash("このお支払いはすでに注文済みです。", "success")
        return redirect(url_for("order_complete"))

    stripe_key = get_stripe_secret_key()
    if stripe_key is None:
        flash("Stripe キーが設定されていません。", "error")
        return redirect(url_for("checkout"))

    stripe.api_key = stripe_key
    try:
        checkout_session = stripe.checkout.Session.retrieve(stripe_session_id)
    except Exception as exc:
        flash(f"決済情報の確認に失敗しました: {exc}", "error")
        return redirect(url_for("cart"))

    if checkout_session.payment_status != "paid":
        flash("支払いが完了していません。", "error")
        return redirect(url_for("checkout"))

    shipping = session.get("pending_shipping")
    if not shipping:
        flash("配送先情報が見つかりません。もう一度お試しください。", "error")
        return redirect(url_for("checkout"))

    items, subtotal, shipping_fee, total = cart_summary()
    if not items:
        flash("カートが空です。もう一度お試しください。", "error")
        return redirect(url_for("products"))

    pending_total = session.get("pending_total")
    if pending_total is not None and pending_total != total:
        flash("カート内容が変わったため、注文を確定できませんでした。", "error")
        return redirect(url_for("cart"))

    if (
        checkout_session.amount_total is not None
        and checkout_session.amount_total != total
    ):
        flash("支払金額と注文合計が一致しません。", "error")
        return redirect(url_for("cart"))

    order_id = create_order(
        items,
        subtotal,
        shipping_fee,
        total,
        user_id,
        shipping,
        stripe_session_id=stripe_session_id,
    )
    if order_id is None:
        flash("在庫が足りない商品があるため、注文を確定できませんでした。", "error")
        return redirect(url_for("cart"))

    try:
        subject, body = build_order_confirmation_email(
            order_id, items, subtotal, shipping_fee, total, shipping
        )
        send_order_confirmation_email(shipping["email"], subject, body)
    except Exception:
        flash(
            "注文は完了しましたが、確認メールの作成に失敗しました。",
            "error",
        )

    session["last_order_id"] = order_id
    session.pop("cart", None)
    session.pop("last_order", None)
    session.pop("pending_shipping", None)
    session.pop("pending_total", None)

    flash("お支払いと注文が完了しました。", "success")
    return redirect(url_for("order_complete"))


@app.route("/order/payment-cancel")
def payment_cancel():
    flash("支払いがキャンセルされました。", "error")
    return redirect(url_for("checkout"))


@app.route("/order/complete")
def order_complete():
    user_id = current_user_id()
    if user_id is None:
        return redirect(url_for("login"))

    order_id = session.get("last_order_id")
    if order_id is None:
        return redirect(url_for("products"))

    order_row = get_order(order_id)
    if order_row is None or order_row["user_id"] != user_id:
        return redirect(url_for("products"))

    items = get_order_items(order_id)
    return render_template(
        "order_complete.html",
        order=order_row,
        items=items,
    )


@app.route("/orders")
def orders():
    user_id = current_user_id()
    if user_id is None:
        return redirect(url_for("login"))

    return render_template(
        "orders.html",
        orders=get_orders_for_user(user_id),
    )


@app.route("/orders/<int:order_id>/cancel", methods=["POST"])
def order_cancel(order_id):
    user_id = current_user_id()
    if user_id is None:
        flash("ログインが必要です。", "error")
        return redirect(url_for("login"))

    ok, error = cancel_order_by_user(order_id, user_id)
    if ok:
        flash("注文をキャンセルし、在庫を戻しました。", "success")
    else:
        flash(error, "error")
    return redirect(url_for("orders"))


@app.route("/contact", methods=["GET", "POST"])
def contact():
    form = {
        "name": "",
        "email": "",
        "message": "",
    }
    if current_user_id() is not None:
        form["name"] = session.get("username") or ""

    error = None
    if request.method == "POST":
        form["name"] = request.form.get("name", "").strip()
        form["email"] = request.form.get("email", "").strip()
        form["message"] = request.form.get("message", "").strip()
        if not form["name"] or not form["email"] or not form["message"]:
            error = "氏名・メールアドレス・お問い合わせ内容をすべて入力してください。"
        else:
            contact_id = save_contact(
                form["name"],
                form["email"],
                form["message"],
                user_id=current_user_id(),
            )
            print_contact_message(
                contact_id, form["name"], form["email"], form["message"]
            )
            flash("お問い合わせを受け付けました。ありがとうございました。", "success")
            return redirect(url_for("contact"))

    return render_template("contact.html", form=form, error=error)


@app.route("/admin/users/new", methods=["GET", "POST"])
def admin_user_new():
    blocked = require_admin()
    if blocked is not None:
        return blocked

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        if not username or not email or not password:
            error = "ユーザー名・メールアドレス・パスワードを入力してください。"
        elif not is_valid_email(email):
            error = "メールアドレスの形式が正しくありません。"
        elif len(password) < MIN_PASSWORD_LENGTH:
            error = f"パスワードは{MIN_PASSWORD_LENGTH}文字以上にしてください。"
        else:
            user_id = create_user(username, password, email, role="admin")
            if user_id is None:
                if get_user_by_username(username) is not None:
                    error = "そのユーザー名はすでに使われています。"
                else:
                    error = "そのメールアドレスはすでに使われています。"
            else:
                flash(f"管理者「{username}」を追加しました。", "success")
                return redirect(url_for("admin_user_new"))

    return render_template(
        "admin_user_new.html",
        error=error,
        admins=get_admin_users(),
        current_user_id=current_user_id(),
    )


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
def admin_user_delete(user_id):
    blocked = require_admin()
    if blocked is not None:
        return blocked

    ok, message = delete_admin_user(user_id, current_user_id())
    flash(message, "success" if ok else "error")
    return redirect(url_for("admin_user_new"))


@app.route("/admin/contacts")
def admin_contacts():
    blocked = require_admin()
    if blocked is not None:
        return blocked

    return render_template(
        "admin_contacts.html",
        contacts=get_all_contacts(),
    )


@app.route("/admin/orders")
def admin_orders():
    blocked = require_admin()
    if blocked is not None:
        return blocked

    return render_template(
        "admin_orders.html",
        orders=get_all_orders(),
        statuses=ORDER_STATUSES,
    )


@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
def admin_order_status(order_id):
    blocked = require_admin()
    if blocked is not None:
        return blocked

    status = request.form.get("status", "").strip()
    if update_order_status(order_id, status):
        flash("注文ステータスを更新しました。", "success")
    else:
        flash("ステータスの更新に失敗しました。", "error")
    return redirect(url_for("admin_orders"))


if __name__ == "__main__":
    init_db()
    app.run(port=8000, debug=True)
