from flask import Flask, abort, redirect, render_template, session, url_for

app = Flask(__name__)
app.secret_key = "freshberrymarket-dev-secret"

PRODUCTS = [
    {
        "id": 1,
        "name": "ブルーベリー 500g",
        "price": 1200,
        "description": "収穫したての生ブルーベリー。そのまま食べてもおいしいです。",
    },
    {
        "id": 2,
        "name": "ブルーベリー 1kg",
        "price": 2200,
        "description": "たっぷり1kg。冷凍保存にもおすすめです。",
    },
    {
        "id": 3,
        "name": "ジャムセット",
        "price": 1800,
        "description": "自家製ブルーベリージャムの詰め合わせです。",
    },
]


def get_product(product_id):
    for product in PRODUCTS:
        if product["id"] == product_id:
            return product
    return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/products")
def products():
    return render_template("products.html", products=PRODUCTS)


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
                "name": product["name"],
                "price": product["price"],
                "quantity": quantity,
                "subtotal": subtotal,
            }
        )

    return render_template("cart.html", items=items, total=total)


if __name__ == "__main__":
    app.run(port=8000, debug=True)
