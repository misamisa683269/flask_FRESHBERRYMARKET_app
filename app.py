from flask import Flask, render_template

app = Flask(__name__)

PRODUCTS = [
    {"name": "ブルーベリー 500g", "price": 1200},
    {"name": "ブルーベリー 1kg", "price": 2200},
    {"name": "ジャムセット", "price": 1800},
]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/products")
def products():
    return render_template("products.html", products=PRODUCTS)


if __name__ == "__main__":
    app.run(port=8000, debug=True)
