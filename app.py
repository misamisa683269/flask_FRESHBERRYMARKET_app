from flask import Flask, abort, render_template

app = Flask(__name__)

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


if __name__ == "__main__":
    app.run(port=8000, debug=True)
