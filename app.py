import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

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
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "freshberrymarket-dev-secret"

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "products.db"
UPLOAD_DIR = BASE_DIR / "uploads"
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

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
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    order_columns = [
        row[1] for row in conn.execute("PRAGMA table_info(orders)").fetchall()
    ]
    if "user_id" not in order_columns:
        conn.execute("ALTER TABLE orders ADD COLUMN user_id INTEGER")
    for column in ("recipient_name", "postal_code", "address", "phone"):
        if column not in order_columns:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {column} TEXT")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            subtotal INTEGER NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders (id)
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
            INSERT INTO users (username, password_hash, role)
            VALUES (?, ?, ?)
            """,
            ("admin", generate_password_hash("admin123"), "admin"),
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


def create_user(username, password, role="user"):
    conn = get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO users (username, password_hash, role)
            VALUES (?, ?, ?)
            """,
            (username, generate_password_hash(password), role),
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
        SELECT id, username, password_hash, role
        FROM users
        WHERE username = ?
        """,
        (username,),
    ).fetchone()
    conn.close()
    return user


def create_order(items, total, user_id, shipping):
    conn = get_db()

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
            recipient_name, postal_code, address, phone
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            total,
            datetime.now().isoformat(timespec="seconds"),
            user_id,
            shipping["recipient_name"],
            shipping["postal_code"],
            shipping["address"],
            shipping["phone"],
        ),
    )
    order_id = cursor.lastrowid
    conn.executemany(
        """
        INSERT INTO order_items (order_id, name, price, quantity, subtotal)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (order_id, item["name"], item["price"], item["quantity"], item["subtotal"])
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


def get_order(order_id):
    conn = get_db()
    order = conn.execute(
        """
        SELECT id, total, created_at, user_id,
               recipient_name, postal_code, address, phone
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
        SELECT name, price, quantity, subtotal
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
               recipient_name, postal_code, address, phone
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
            SELECT name, price, quantity, subtotal
            FROM order_items
            WHERE order_id = ?
            ORDER BY id
            """,
            (order["id"],),
        ).fetchall()
        result.append({"order": order, "order_items": items})
    conn.close()
    return result


def build_cart_items():
    cart_data = session.get("cart", {})
    items = []
    total = 0

    for product_id, quantity in cart_data.items():
        product = get_product(int(product_id))
        if product is None:
            continue
        subtotal = product["price"] * quantity
        total += subtotal
        items.append(
            {
                "id": product["id"],
                "name": product["name"],
                "price": product["price"],
                "quantity": quantity,
                "subtotal": subtotal,
                "stock": product["stock"] if product["stock"] is not None else 0,
            }
        )

    return items, total


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
        password = request.form.get("password", "")
        if not username or not password:
            error = "ユーザー名とパスワードを入力してください。"
        else:
            user_id = create_user(username, password)
            if user_id is None:
                error = "そのユーザー名はすでに使われています。"
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


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("username", None)
    session.pop("role", None)
    flash("ログアウトしました。", "success")
    return redirect(url_for("index"))


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
    return render_template(
        "products.html",
        products=product_list,
        q=query,
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
    return render_template("product_detail.html", product=product)


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
    items, total = build_cart_items()
    return render_template("cart.html", items=items, total=total)


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

    items, total = build_cart_items()
    if not items:
        flash("カートが空です。", "error")
        return redirect(url_for("cart"))

    return render_template("checkout.html", items=items, total=total, error=None)


@app.route("/order", methods=["POST"])
def order():
    user_id = current_user_id()
    if user_id is None:
        flash("注文するにはログインが必要です。", "error")
        return redirect(url_for("login"))

    items, total = build_cart_items()
    if not items:
        flash("カートが空です。", "error")
        return redirect(url_for("cart"))

    shipping = {
        "recipient_name": request.form.get("recipient_name", "").strip(),
        "postal_code": request.form.get("postal_code", "").strip(),
        "address": request.form.get("address", "").strip(),
        "phone": request.form.get("phone", "").strip(),
    }

    if not all(shipping.values()):
        return render_template(
            "checkout.html",
            items=items,
            total=total,
            error="氏名・郵便番号・住所・電話番号をすべて入力してください。",
        )

    order_id = create_order(items, total, user_id, shipping)
    if order_id is None:
        flash("在庫が足りない商品があるため、注文できませんでした。", "error")
        return redirect(url_for("cart"))

    session["last_order_id"] = order_id
    session.pop("cart", None)
    session.pop("last_order", None)

    flash("注文が完了しました。", "success")
    return redirect(url_for("order_complete"))


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
        total=order_row["total"],
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


if __name__ == "__main__":
    init_db()
    app.run(port=8000, debug=True)
