import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = "freshberrymarket-dev-secret"

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "products.db"

SEED_PRODUCTS = [
    (
        "ブルーベリー 500g",
        1200,
        "収穫したての生ブルーベリー。そのまま食べてもおいしいです。",
    ),
    (
        "ブルーベリー 1kg",
        2200,
        "たっぷり1kg。冷凍保存にもおすすめです。",
    ),
    (
        "ジャムセット",
        1800,
        "自家製ブルーベリージャムの詰め合わせです。",
    ),
]


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            description TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
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
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    order_columns = [
        row[1] for row in conn.execute("PRAGMA table_info(orders)").fetchall()
    ]
    if "user_id" not in order_columns:
        conn.execute("ALTER TABLE orders ADD COLUMN user_id INTEGER")

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
            "INSERT INTO products (name, price, description) VALUES (?, ?, ?)",
            SEED_PRODUCTS,
        )
    conn.commit()
    conn.close()


def get_all_products():
    conn = get_db()
    products = conn.execute(
        "SELECT id, name, price, description FROM products ORDER BY id"
    ).fetchall()
    conn.close()
    return products


def get_product(product_id):
    conn = get_db()
    product = conn.execute(
        "SELECT id, name, price, description FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()
    conn.close()
    return product


def create_user(username, password):
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password)),
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
        "SELECT id, username, password_hash FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    conn.close()
    return user


def create_order(items, total, user_id):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO orders (total, created_at, user_id) VALUES (?, ?, ?)",
        (total, datetime.now().isoformat(timespec="seconds"), user_id),
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
    conn.commit()
    conn.close()
    return order_id


def get_order(order_id):
    conn = get_db()
    order = conn.execute(
        "SELECT id, total, created_at, user_id FROM orders WHERE id = ?",
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
        SELECT id, total, created_at, user_id
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
            }
        )

    return items, total


def current_user_id():
    return session.get("user_id")


@app.context_processor
def inject_auth():
    return {
        "current_username": session.get("username"),
        "is_logged_in": current_user_id() is not None,
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
            return redirect(url_for("index"))
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("username", None)
    return redirect(url_for("index"))


@app.route("/products")
def products():
    return render_template("products.html", products=get_all_products())


@app.route("/products/<int:product_id>")
def product_detail(product_id):
    product = get_product(product_id)
    if product is None:
        abort(404)
    return render_template("product_detail.html", product=product)


@app.route("/cart/add/<int:product_id>", methods=["POST"])
def cart_add(product_id):
    product = get_product(product_id)
    if product is None:
        abort(404)

    cart = session.get("cart", {})
    key = str(product_id)
    cart[key] = cart.get(key, 0) + 1
    session["cart"] = cart

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

    quantity = request.form.get("quantity", type=int)
    cart = session.get("cart", {})
    key = str(product_id)

    if quantity is None or quantity < 1:
        cart.pop(key, None)
    else:
        cart[key] = quantity

    session["cart"] = cart
    return redirect(url_for("cart"))


@app.route("/cart/remove/<int:product_id>", methods=["POST"])
def cart_remove(product_id):
    cart = session.get("cart", {})
    cart.pop(str(product_id), None)
    session["cart"] = cart
    return redirect(url_for("cart"))


@app.route("/order", methods=["POST"])
def order():
    user_id = current_user_id()
    if user_id is None:
        return redirect(url_for("login"))

    items, total = build_cart_items()
    if not items:
        return redirect(url_for("cart"))

    order_id = create_order(items, total, user_id)
    session["last_order_id"] = order_id
    session.pop("cart", None)
    session.pop("last_order", None)

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
