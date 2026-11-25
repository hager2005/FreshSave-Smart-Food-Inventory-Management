from datetime import date, datetime
from pathlib import Path
import sqlite3

from flask import Flask, flash, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "freshsave.db"
app = Flask(__name__)
app.secret_key = "freshsave-local-development-key"


def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity >= 0),
                price REAL NOT NULL CHECK(price >= 0),
                expiry_date TEXT NOT NULL,
                suggested_discount INTEGER NOT NULL DEFAULT 0,
                approved_discount INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active'
            );
        """)


def parse_expiry(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def expiry_details(expiry_text, today=None):
    today = today or date.today()
    remaining = (parse_expiry(expiry_text) - today).days
    if remaining < 0:
        return remaining, "expired", "منتهية"
    if remaining <= 3:
        return remaining, "urgent", "عاجلة"
    if remaining <= 14:
        return remaining, "soon", "قريبة الانتهاء"
    return remaining, "healthy", "آمنة"


def suggested_discount(days):
    if days < 0:
        return 0
    if days <= 3:
        return 30
    if days <= 7:
        return 20
    if days <= 14:
        return 10
    return 0


@app.template_filter("money")
def money(value):
    return f"{float(value):,.2f} ج.م"


@app.route("/")
def index():
    with get_db() as db:
        products = db.execute("SELECT * FROM products ORDER BY expiry_date, name").fetchall()

    today = date.today()
    urgent_count = 0
    soon_count = 0
    expired_count = 0
    enriched = []
    for product in products:
        item = dict(product)
        remaining, category, label = expiry_details(item["expiry_date"], today)
        item.update({
            "remaining": remaining,
            "category": category,
            "category_label": label,
            "suggested_discount": suggested_discount(remaining),
        })
        enriched.append(item)
        if category == "urgent":
            urgent_count += item["quantity"] > 0
        elif category == "soon":
            soon_count += item["quantity"] > 0
        elif category == "expired":
            expired_count += item["quantity"] > 0

    counts = {
        "total": sum(int(p["quantity"] > 0) for p in enriched),
        "urgent": urgent_count,
        "soon": soon_count,
        "expired": expired_count,
    }
    return render_template("index.html", products=enriched, counts=counts, today=today)


@app.route("/products/add", methods=["POST"])
def add_product():
    try:
        name = request.form["name"].strip()
        quantity = int(request.form["quantity"])
        price = float(request.form["price"])
        expiry_text = request.form["expiry_date"]
        expiry = parse_expiry(expiry_text)
        if not name or quantity < 0 or price < 0:
            raise ValueError
        if expiry < date.today():
            flash("تحذير سلامة الغذاء: لا يُسجّل تاريخ صلاحية منتهي للبيع.", "error")
            return redirect(url_for("index"))
    except (KeyError, ValueError):
        flash("تأكد من إدخال بيانات المنتج بشكل صحيح.", "error")
        return redirect(url_for("index"))

    discount = suggested_discount((expiry - date.today()).days)
    with get_db() as db:
        db.execute("""
            INSERT INTO products (name, quantity, price, expiry_date, suggested_discount)
            VALUES (?, ?, ?, ?, ?)
        """, (name, quantity, price, expiry_text, discount))
    flash("تمت إضافة المنتج بنجاح.", "success")
    return redirect(url_for("index"))


@app.route("/products/<int:product_id>/discount", methods=["POST"])
def approve_discount(product_id):
    try:
        discount = int(request.form["discount"])
        if discount < 0 or discount > 90:
            raise ValueError
    except (KeyError, ValueError):
        flash("نسبة التخفيض غير صحيحة.", "error")
        return redirect(url_for("index"))

    with get_db() as db:
        product = db.execute("SELECT expiry_date FROM products WHERE id = ?", (product_id,)).fetchone()
        if product and parse_expiry(product["expiry_date"]) >= date.today():
            db.execute("UPDATE products SET approved_discount = ? WHERE id = ?", (discount, product_id))
            flash("تم اعتماد التخفيض.", "success")
        else:
            flash("لا يمكن خصم منتج منتهي الصلاحية.", "error")
    return redirect(url_for("index"))


@app.route("/products/<int:product_id>/delete", methods=["POST"])
def delete_product(product_id):
    with get_db() as db:
        db.execute("DELETE FROM products WHERE id = ?", (product_id,))
    flash("تم حذف المنتج.", "success")
    return redirect(url_for("index"))


@app.route("/reports")
def reports():
    with get_db() as db:
        discounted = db.execute("SELECT * FROM products WHERE approved_discount > 0 ORDER BY expiry_date").fetchall()
    return render_template("reports.html", discounted=discounted)


init_db()


if __name__ == "__main__":
    app.run(debug=True)
