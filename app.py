import json
import os
import sqlite3
import time
from datetime import datetime, timedelta
import midtransclient

from flask import Flask, render_template, request, redirect, url_for, session, g, send_from_directory, flash, jsonify
from werkzeug.utils import secure_filename


app = Flask(__name__)
# Load env for Gemini
from dotenv import load_dotenv
load_dotenv()

app.secret_key = "dev"
app.config["DATABASE"] = os.path.join(app.root_path, "sukaikan.db")
app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "uploads")
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Midtrans Configuration
# Replacing with actual sandbox keys is recommended, but for demo we use placeholders
MIDTRANS_SERVER_KEY = "SB-Mid-server-YOUR_SERVER_KEY_HERE"
MIDTRANS_CLIENT_KEY = "SB-Mid-client-YOUR_CLIENT_KEY_HERE"

snap = midtransclient.Snap(
    is_production=False,
    server_key=MIDTRANS_SERVER_KEY,
    client_key=MIDTRANS_CLIENT_KEY
)


# === Gemini AI Configuration ===
import google.generativeai as genai

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Define system instruction for SUKAIKAN AI Expert
SYSTEM_INSTRUCTION = """
Kamu adalah IKAN AI, asisten virtual dan pakar ikan untuk toko online SUKAIKAN.
Format jawabanmu menggunakan HTML dasar (contoh: <strong>, <br>, <em>) agar rapi di web.
SUKAIKAN menjual ikan laut berkualitas tinggi, diproses di Cold Storage, dijamin segar atau uang kembali.
Tugas utamamu:
1. Memberikan informasi gizi ikan (kalori, protein, omega-3, dll).
2. Memberikan resep masakan ikan yang praktis.
3. Mencocokkan pertanyaan dengan produk jika relevan.

Jawablah dengan ramah, informatif, dan ringkas. Gunakan emoji yang relevan.
Jika ada yang bertanya di luar topik ikan, makanan, atau SUKAIKAN, tolak dengan sopan dan kembalikan ke topik ikan.
"""
# ===============================

@app.context_processor
def inject_cart_count():
    cart = session.get("cart", {})
    count = sum(cart.values())
    return dict(cart_count=count)


# --- Initial Data for Seeding ---
INITIAL_PRODUCTS = [
    {
        "id": "kembung-fillet",
        "nama": "Ikan Kembung Fillet",
        "kategori": "ikan-laut",
        "harga_per_kg": 48000,
        "label_musim": "Fresh Minggu Ini",
        "ukuran": "Sedang, 8–10 ekor/kg",
        "tekstur": "Daging lembut, cocok untuk goreng dan bakar",
    },
    {
        "id": "tongkol-segar",
        "nama": "Ikan Tongkol Segar",
        "kategori": "ikan-laut",
        "harga_per_kg": 42000,
        "label_musim": "Fresh Minggu Ini",
        "ukuran": "Sedang, 3–4 ekor/kg",
        "tekstur": "Padat dan gurih, cocok untuk balado",
    },
    {
        "id": "udang-vaname",
        "nama": "Udang Vaname",
        "kategori": "udang-cumi",
        "harga_per_kg": 78000,
        "label_musim": "",
        "ukuran": "Sedang, 50–60 ekor/kg",
        "tekstur": "Renya, manis, cocok untuk tumis dan goreng tepung",
    },
    {
        "id": "cumi-tube",
        "nama": "Cumi Tube",
        "kategori": "udang-cumi",
        "harga_per_kg": 85000,
        "label_musim": "",
        "ukuran": "Sedang, 10–15 potong/kg",
        "tekstur": "Empuk jika dimasak singkat, cocok untuk calamari",
    },
    {
        "id": "kerang-hijau",
        "nama": "Kerang Hijau",
        "kategori": "kerang",
        "harga_per_kg": 28000,
        "label_musim": "Fresh Minggu Ini",
        "ukuran": "Campur, 60–80 butir/kg",
        "tekstur": "Kenyal, gurih, cocok untuk rebus dan tumis",
    },
]

INITIAL_RECOMMENDATIONS = [
    {"product_id": "kembung-fillet", "nama": "Ikan Kembung Goreng Kunyit", "estimasi": "20 menit"},
    {"product_id": "kembung-fillet", "nama": "Kembung Bakar Sambal Matah", "estimasi": "30 menit"},
    {"product_id": "tongkol-segar", "nama": "Tongkol Balado Rumahan", "estimasi": "35 menit"},
    {"product_id": "tongkol-segar", "nama": "Tongkol Suwir Pedas", "estimasi": "25 menit"},
    {"product_id": "udang-vaname", "nama": "Udang Saus Padang", "estimasi": "30 menit"},
    {"product_id": "udang-vaname", "nama": "Udang Goreng Tepung Krispi", "estimasi": "25 menit"},
    {"product_id": "cumi-tube", "nama": "Cumi Goreng Tepung", "estimasi": "20 menit"},
    {"product_id": "cumi-tube", "nama": "Cumi Saus Tiram", "estimasi": "25 menit"},
    {"product_id": "kerang-hijau", "nama": "Kerang Hijau Rebus Bumbu Kencur", "estimasi": "25 menit"},
    {"product_id": "kerang-hijau", "nama": "Kerang Hijau Saus Padang", "estimasi": "30 menit"},
]

INITIAL_BATCH = {
    "nama": "Batch Akhir Pekan",
    "tanggal_pengiriman": "Sabtu, 14 Februari",
    "status": "Buka",
    "countdown": "1:03:12:45",
}


def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = sqlite3.connect(app.config["DATABASE"])
        db.row_factory = sqlite3.Row
        g._db = db
    return db


@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    # Orders Table (Existing)
    db.execute(
        """
        create table if not exists orders (
            id integer primary key autoincrement,
            nama text,
            hp text,
            alamat text,
            kecamatan text,
            metode_bayar text,
            total integer,
            status text,
            tanggal_pengiriman text,
            items_json text,
            bukti_path text,
            created_at text
        )
        """
    )
    
    # Products Table (New)
    db.execute(
        """
        create table if not exists products (
            id text primary key,
            nama text,
            kategori text,
            harga_per_kg integer,
            label_musim text,
            ukuran text,
            tekstur text,
            image_path text,
            is_active integer default 1
        )
        """
    )
    
    # Migration: Check if image_path exists in products, if not add it
    try:
        db.execute("select image_path from products limit 1")
    except sqlite3.OperationalError:
        db.execute("alter table products add column image_path text")

    # Recommendations Table (New)
    db.execute(
        """
        create table if not exists recommendations (
            id integer primary key autoincrement,
            product_id text,
            nama text,
            estimasi text,
            foreign key(product_id) references products(id)
        )
        """
    )

    # Batches Table (New)
    db.execute(
        """
        create table if not exists batches (
            id integer primary key autoincrement,
            nama text,
            tanggal_pengiriman text,
            status text,
            countdown text,
            deadline text,
            is_active integer default 0
        )
        """
    )
    
    # Migration: Check if deadline exists in batches, if not add it
    try:
        db.execute("select deadline from batches limit 1")
    except sqlite3.OperationalError:
        db.execute("alter table batches add column deadline text")
    
    # Migration: Check if payment_deadline exists in orders, if not add it
    try:
        db.execute("select payment_deadline from orders limit 1")
    except sqlite3.OperationalError:
        db.execute("alter table orders add column payment_deadline text")
        
    db.commit()
    seed_data(db)


@app.route("/admin/produk/tambah", methods=["GET", "POST"])
def admin_tambah_produk():
    if request.method == "POST":
        nama = request.form.get("nama")
        kategori = request.form.get("kategori")
        harga = request.form.get("harga_per_kg")
        ukuran = request.form.get("ukuran")
        tekstur = request.form.get("tekstur")
        
        # Generate ID from name
        product_id = nama.lower().replace(" ", "-")
        
        # Handle Image Upload
        image_path = ""
        file = request.files.get("image")
        if file and file.filename:
            filename = secure_filename(file.filename)
            ext = os.path.splitext(filename)[1]
            if not ext: ext = ".jpg"
            # use product_id as filename for uniqueness
            new_filename = f"{product_id}_{int(time.time())}{ext}"
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], new_filename)
            file.save(filepath)
            image_path = new_filename

        db = get_db()
        db.execute(
            "insert into products (id, nama, kategori, harga_per_kg, ukuran, tekstur, label_musim, image_path, is_active) values (?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (product_id, nama, kategori, harga, ukuran, tekstur, "", image_path)
        )
        db.commit()
        return redirect(url_for("admin_dashboard"))
    return render_template("product_form.html", action="Tambah")


@app.route("/admin/produk/edit/<product_id>", methods=["GET", "POST"])
def admin_edit_produk(product_id):
    db = get_db()
    if request.method == "POST":
        nama = request.form.get("nama")
        kategori = request.form.get("kategori")
        harga = request.form.get("harga_per_kg")
        ukuran = request.form.get("ukuran")
        tekstur = request.form.get("tekstur")
        label_musim = request.form.get("label_musim", "")
        
        # Handle Image Upload
        file = request.files.get("image")
        if file and file.filename:
            filename = secure_filename(file.filename)
            ext = os.path.splitext(filename)[1]
            if not ext: ext = ".jpg"
            new_filename = f"{product_id}_{int(time.time())}{ext}"
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], new_filename)
            file.save(filepath)
            
            # Update with new image
            db.execute(
                "update products set nama=?, kategori=?, harga_per_kg=?, ukuran=?, tekstur=?, label_musim=?, image_path=? where id=?",
                (nama, kategori, harga, ukuran, tekstur, label_musim, new_filename, product_id)
            )
        else:
            # Update without changing image
            db.execute(
                "update products set nama=?, kategori=?, harga_per_kg=?, ukuran=?, tekstur=?, label_musim=? where id=?",
                (nama, kategori, harga, ukuran, tekstur, label_musim, product_id)
            )
            
        db.commit()
        return redirect(url_for("admin_dashboard"))
        
    product = db.execute("select * from products where id = ?", (product_id,)).fetchone()
    return render_template("product_form.html", action="Edit", product=product)


def seed_data(db):
    # Seed Products if empty
    product_count = db.execute("select count(*) from products").fetchone()[0]
    if product_count == 0:
        for p in INITIAL_PRODUCTS:
            db.execute(
                "insert into products (id, nama, kategori, harga_per_kg, label_musim, ukuran, tekstur) values (?, ?, ?, ?, ?, ?, ?)",
                (p["id"], p["nama"], p["kategori"], p["harga_per_kg"], p["label_musim"], p["ukuran"], p["tekstur"])
            )
        
        for r in INITIAL_RECOMMENDATIONS:
            db.execute(
                "insert into recommendations (product_id, nama, estimasi) values (?, ?, ?)",
                (r["product_id"], r["nama"], r["estimasi"])
            )
        db.commit()

    # Seed Batch if empty
    batch_count = db.execute("select count(*) from batches").fetchone()[0]
    if batch_count == 0:
        db.execute(
            "insert into batches (nama, tanggal_pengiriman, status, countdown, is_active) values (?, ?, ?, ?, 1)",
            (INITIAL_BATCH["nama"], INITIAL_BATCH["tanggal_pengiriman"], INITIAL_BATCH["status"], INITIAL_BATCH["countdown"])
        )
        db.commit()


def get_active_batch():
    db = get_db()
    batch = db.execute("select * from batches where is_active = 1 order by id desc limit 1").fetchone()
    if batch:
        b = dict(batch)
        
        # Auto-Migration: If deadline is missing but countdown exists, set deadline from now + duration
        if not b.get("deadline") and b.get("countdown"):
            try:
                parts = b["countdown"].split(":")
                if len(parts) == 4: # D:HH:MM:SS
                    days = int(parts[0])
                    hours = int(parts[1])
                    minutes = int(parts[2])
                    seconds = int(parts[3])
                elif len(parts) == 3: # HH:MM:SS (old format, 0 days)
                    days = 0
                    hours = int(parts[0])
                    minutes = int(parts[1])
                    seconds = int(parts[2])
                else:
                     raise ValueError("Unknown format")
                
                deadline = datetime.now() + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
                deadline_str = deadline.isoformat()
                
                # Update DB
                db.execute("update batches set deadline = ? where id = ?", (deadline_str, b["id"]))
                db.commit()
                b["deadline"] = deadline_str
                
            except Exception as e:
                print(f"Error migrating countdown to deadline: {e}")

        # Calculate dynamic countdown based on deadline
        if b.get("deadline"):
            try:
                deadline = datetime.fromisoformat(b["deadline"])
                now = datetime.now()
                remaining = deadline - now
                total_seconds = int(remaining.total_seconds())
                
                if total_seconds > 0:
                    days = total_seconds // 86400
                    rem = total_seconds % 86400
                    hours = rem // 3600
                    rem = rem % 3600
                    minutes = rem // 60
                    seconds = rem % 60
                    # Format for frontend JS: D:HH:MM:SS
                    b["countdown"] = f"{days}:{hours:02d}:{minutes:02d}:{seconds:02d}"
                else:
                    b["countdown"] = "0:00:00:00"
            except ValueError:
                pass # fallback to static countdown if parsing fails

        if not b.get("countdown"):
            b["countdown"] = "0:00:00:00"
        return b
    return INITIAL_BATCH  # Fallback if DB issue


def get_all_products(category=None, search_query=None):
    db = get_db()
    query = "select * from products where is_active = 1"
    params = []
    
    if category:
        query += " and kategori = ?"
        params.append(category)
    
    if search_query:
        query += " and nama like ?"
        params.append(f"%{search_query}%")
        
    rows = db.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_product_by_id(product_id):
    db = get_db()
    row = db.execute("select * from products where id = ?", (product_id,)).fetchone()
    if row:
        return dict(row)
    return None


def get_recommendations(product_id):
    db = get_db()
    rows = db.execute("select * from recommendations where product_id = ?", (product_id,)).fetchall()
    return [dict(row) for row in rows]


def get_cart():
    return session.get("cart", {})


def save_cart(cart):
    session["cart"] = cart


def build_order_items(cart):
    items = []
    total = 0
    for product_id, qty in cart.items():
        product = get_product_by_id(product_id)
        if not product:
            continue
        subtotal = product["harga_per_kg"] * qty
        total += subtotal
        items.append(
            {
                "product_id": product_id,
                "product": product,
                "nama": product["nama"],
                "harga_per_kg": product["harga_per_kg"],
                "qty": qty,
                "subtotal": subtotal,
            }
        )
    return items, total


def serialize_items_for_db(items):
    data = []
    for item in items:
        data.append(
            {
                "product_id": item["product_id"],
                "nama": item["nama"],
                "harga_per_kg": item["harga_per_kg"],
                "qty": item["qty"],
                "subtotal": item["subtotal"],
            }
        )
    return json.dumps(data)


@app.route("/")
def beranda():
    batch = get_active_batch()
    # Seasonal products query (has label_musim)
    db = get_db()
    rows = db.execute("select * from products where is_active = 1 and label_musim != ''").fetchall()
    produk_musim = [dict(row) for row in rows]
    
    return render_template(
        "beranda.html",
        batch=batch,
        produk_musim=produk_musim,
    )


@app.route("/katalog")
def katalog():
    kategori = request.args.get("kategori", "")
    q = request.args.get("q", "").strip()
    
    products = get_all_products(category=kategori, search_query=q)
    
    return render_template(
        "katalog.html",
        produk=products,
        kategori=kategori,
        q=q,
    )


@app.route("/produk/<product_id>")
def detail_produk(product_id):
    product = get_product_by_id(product_id)
    if not product:
        return redirect(url_for("katalog"))
    rekomendasi = get_recommendations(product_id)
    return render_template(
        "detail_produk.html",
        product=product,
        rekomendasi=rekomendasi,
    )


@app.route("/keranjang")
def keranjang():
    cart = get_cart()
    items, total = build_order_items(cart)
    return render_template(
        "keranjang.html",
        items=items,
        total=total,
    )


@app.route("/keranjang/tambah", methods=["POST"])
def tambah_ke_keranjang():
    product_id = request.form.get("product_id")
    qty = request.form.get("qty", "1")
    try:
        qty = int(qty)
    except ValueError:
        qty = 1
    if qty < 1:
        qty = 1
        
    product = get_product_by_id(product_id)
    if not product:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "message": "Produk tidak ditemukan."}), 404
        return redirect(url_for("katalog"))
        
    cart = get_cart()
    cart[product_id] = cart.get(product_id, 0) + qty
    save_cart(cart)
    
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        # Calculate new total count
        cart_count = sum(cart.values())
        return jsonify({
            "success": True, 
            "message": f"{qty}kg {product['nama']} ditambah ke keranjang.", 
            "cart_count": cart_count
        })
    
    next_url = request.form.get("next") or url_for("keranjang")
    return redirect(next_url)


@app.route("/keranjang/hapus", methods=["POST"])
def hapus_dari_keranjang():
    product_id = request.form.get("product_id")
    cart = get_cart()
    
    if product_id in cart:
        del cart[product_id]
        save_cart(cart)
        
    return redirect(url_for("keranjang"))


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart = get_cart()
    if not cart:
        return redirect(url_for("katalog"))
        
    batch = get_active_batch()
    
    if request.method == "POST":
        nama = request.form.get("nama", "").strip()
        hp = request.form.get("hp", "").strip()
        
        # New Share Loc Logic
        maps_link = request.form.get("maps_link", "").strip()
        patokan = request.form.get("patokan", "").strip()
        
        # Format: Link \n\n Patokan
        alamat = f"{maps_link}\n\nPatokan: {patokan}"
        
        kecamatan = "-" # Removed from form
        metode_bayar = request.form.get("metode_bayar", "").strip()
        
        items, total = build_order_items(cart)
        items_json = serialize_items_for_db(items)
        created_at = datetime.utcnow().isoformat()
        status = "Menunggu Pembayaran"
        
        completed_at = None
        payment_deadline = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
        
        db = get_db()
        cursor = db.execute(
            "insert into orders (nama, hp, alamat, kecamatan, metode_bayar, total, status, tanggal_pengiriman, items_json, created_at, payment_deadline) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                nama,
                hp,
                alamat,
                kecamatan,
                metode_bayar,
                total,
                status,
                batch["tanggal_pengiriman"],
                items_json,
                created_at,
                payment_deadline,
            ),
        )
        db.commit()
        
        order_id = cursor.lastrowid
        
        # Create Snap Transaction
        param = {
            "transaction_details": {
                "order_id": f"ORDER-{order_id}-{int(time.time())}", # Unique ID requirement
                "gross_amount": int(total),
            },
            "credit_card": {
                "secure": True
            },
            "customer_details": {
                "first_name": nama,
                "phone": hp,
            }
        }
        
        try:
            if "YOUR_SERVER_KEY" in MIDTRANS_SERVER_KEY:
                # Mock Mode for Demo
                snap_token = "DUMMY_TOKEN_FOR_DEMO"
            else:
                transaction = snap.create_transaction(param)
                snap_token = transaction['token']
                
            session["snap_token"] = snap_token
        except Exception as e:
            print(f"Midtrans Error: {e}")
            snap_token = None
        
        session["last_order_id"] = order_id
        session["last_hp"] = hp
        save_cart({}) # clear cart
        
        return redirect(url_for("berhasil_pesan"))
        
    return render_template(
        "checkout.html",
        batch=batch,
    )


@app.route("/pesanan/berhasil", methods=["GET", "POST"])
def berhasil_pesan():
    order_id = session.get("last_order_id")
    snap_token = session.get("snap_token")
    
    if not order_id:
        return redirect(url_for("katalog"))
        
    db = get_db()
    if request.method == "POST":
        file = request.files.get("bukti")
        if file and file.filename:
            filename = secure_filename(file.filename)
            name, ext = os.path.splitext(filename)
            if not ext:
                ext = ".jpg"
            filename = f"order_{order_id}_{int(time.time())}{ext}"
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            
            db.execute(
                "update orders set bukti_path = ? where id = ?",
                (filename, order_id),
            )
            db.commit()
            
        return redirect(url_for("berhasil_pesan"))
        
    order_row = db.execute("select * from orders where id = ?", (order_id,)).fetchone()
    if not order_row:
         return redirect(url_for("katalog"))
         
    order = dict(order_row)
    
    # Check Expiry
    is_expired = False
    if order.get("payment_deadline"):
        deadline = datetime.fromisoformat(order["payment_deadline"])
        if datetime.utcnow() > deadline and order["status"] == "Menunggu Pembayaran":
            is_expired = True
            # Optional: Update status in DB to 'Dibatalkan'
            # db.execute("update orders set status = 'Dibatalkan' where id = ?", (order_id,))
            # db.commit()
            
    # Reconstruct order object similar to before
    items = json.loads(order["items_json"] or "[]")
    order["items"] = items
            
    return render_template(
        "berhasil_pesan.html",
        order=order,
        snap_token=snap_token,
        client_key=MIDTRANS_CLIENT_KEY,
        is_expired=is_expired
    )


@app.route("/lacak", methods=["GET", "POST"])
def lacak_pesanan():
    hp = ""
    status = ""
    orders = []
    
    if request.method == "POST":
        hp = request.form.get("hp", "").strip()
        if hp:
            db = get_db()
            rows = db.execute(
                "select * from orders where hp = ? order by created_at desc",
                (hp,),
            ).fetchall()
            
            # Convert to list of dicts
            orders = []
            for row in rows:
                o = dict(row)
                # Check expiry for display logic
                o["is_expired"] = False
                if o.get("payment_deadline"):
                    deadline = datetime.fromisoformat(o["payment_deadline"])
                    if datetime.utcnow() > deadline and o["status"] == "Menunggu Pembayaran":
                         o["is_expired"] = True
                         o["status"] = "Dibatalkan (Expired)"
                orders.append(o)
            
            return render_template("lacak.html", hp=hp, orders=orders)
            
    return render_template(
        "lacak.html",
        hp=hp,
        orders=orders,
    )


@app.route("/bayar/<int:order_id>")
def bayar_ulang(order_id):
    db = get_db()
    order = db.execute("select * from orders where id = ?", (order_id,)).fetchone()
    if order:
        # Restore session for berhasil_pesan page
        session["last_order_id"] = order["id"]
        session["last_hp"] = order["hp"]
        
        # Check if creating new token is allowed (not expired)
        o = dict(order)
        if o.get("payment_deadline"):
             deadline = datetime.fromisoformat(o["payment_deadline"])
             if datetime.utcnow() > deadline:
                 # It is expired, do not regenerate token, berhasil_pesan will show expired status
                 pass 
             else:
                 # Not expired, regenerate token to be sure
                 import time
                 param = {
                    "transaction_details": {
                        "order_id": f"ORDER-{order_id}-{int(time.time())}", 
                        "gross_amount": int(o["total"]),
                    },
                    "credit_card": { "secure": True },
                    "customer_details": { "first_name": o["nama"], "phone": o["hp"] }
                }
                 try:
                    if "YOUR_SERVER_KEY" in MIDTRANS_SERVER_KEY:
                        token = "DUMMY_TOKEN_FOR_DEMO"
                    else:
                        transaction = snap.create_transaction(param)
                        token = transaction['token']
                    session["snap_token"] = token
                 except Exception:
                    pass

        return redirect(url_for("berhasil_pesan"))

    return redirect(url_for("lacak_pesanan"))


@app.route("/edukasi")
def edukasi():
    return render_template("edukasi.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        # Simple Hardcoded Credentials
        if username == "admin" and password == "sukaikan":
            session["is_admin"] = True
            flash("Selamat datang, Mitra Nelayan!", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Username atau Password salah.", "error")
            
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("is_admin", None)
    flash("Anda telah keluar.", "info")
    return redirect(url_for("login"))

@app.before_request
def require_login():
    if request.path.startswith("/admin"):
        if not session.get("is_admin"):
            flash("Silakan login terlebih dahulu.", "warning")
            return redirect(url_for("login"))

@app.route("/admin")
def admin_dashboard():
    db = get_db()
    
    # 1. Orders
    rows = db.execute(
        "select * from orders order by created_at desc limit 50"
    ).fetchall()
    orders = [dict(row) for row in rows]
    
    # Stats
    total_penjualan = 0
    total_kg = 0
    for o in orders:
        total_penjualan += (o["total"] or 0)
        items = json.loads(o["items_json"] or "[]")
        o["items_list"] = items # Add this for template
        for item in items:
            total_kg += item.get("qty", 0)
            
        # Parse Maps URL if present
        o["maps_url"] = None
        o["alamat_display"] = o["alamat"]
        
        if o["alamat"] and o["alamat"].startswith("http"):
            # Split by newline first to separate URL from Patokan validation
            parts = o["alamat"].split("\n", 1)
            o["maps_url"] = parts[0].strip()
            o["alamat_display"] = parts[1].strip() if len(parts) > 1 else ""
            
    # 2. Products
    products = get_all_products()
    
    # 3. Batch
    batch = get_active_batch()
    
    # Parse countdown for form pre-fill
    # Format expected: DD:HH:MM:SS or HH:MM:SS
    countdown_parts = {"d": 0, "h": 0, "m": 0}
    if batch and batch["countdown"]:
        parts = batch["countdown"].split(":")
        # Reverse to map from seconds up to days
        parts.reverse()
        
        # Mapping: 0->S (unused in form), 1->M, 2->H, 3->D
        if len(parts) > 1:
            countdown_parts["m"] = int(parts[1])
        if len(parts) > 2:
            countdown_parts["h"] = int(parts[2])
        if len(parts) > 3:
            countdown_parts["d"] = int(parts[3])

    return render_template(
        "admin_dashboard.html",
        orders=orders,
        products=products,
        batch=batch,
        total_penjualan=total_penjualan,
        total_kg=int(total_kg), # Cast to int for display
        countdown=countdown_parts
    )





@app.route("/admin/batch/update", methods=["POST"])
def admin_update_batch():
    nama = request.form.get("nama")
    tanggal = request.form.get("tanggal_pengiriman")
    status = request.form.get("status")
    
    # Construct countdown string
    days = request.form.get("d", "0")
    hours = request.form.get("h", "0")
    minutes = request.form.get("m", "0")
    
    # Pad with zeros
    days = int(days) if days.isdigit() else 0
    hours = int(hours) if hours.isdigit() else 0
    minutes = int(minutes) if minutes.isdigit() else 0
    
    # Calculate Deadline
    now = datetime.now()
    deadline = now + timedelta(days=days, hours=hours, minutes=minutes)
    deadline_str = deadline.isoformat()
    
    # Format: D:HH:MM:00 (Seconds default to 00) - Still used for initial display fallback
    countdown = f"{days}:{hours:02d}:{minutes:02d}:00"
    
    db = get_db()
    # For simplicity, update the active batch or insert if not exists
    # We update all active batches to inactive first if we want strict single batch?
    # For now, let's just update the most recent active one
    
    active_batch = db.execute("select id from batches where is_active = 1 order by id desc limit 1").fetchone()
    
    if active_batch:
        db.execute(
            "update batches set nama=?, tanggal_pengiriman=?, status=?, countdown=?, deadline=? where id=?",
            (nama, tanggal, status, countdown, deadline_str, active_batch["id"])
        )
    else:
        db.execute(
            "insert into batches (nama, tanggal_pengiriman, status, countdown, deadline, is_active) values (?, ?, ?, ?, ?, 1)",
            (nama, tanggal, status, countdown, deadline_str)
        )
    db.commit()
    return redirect(url_for("admin_dashboard"))





@app.route("/admin/update_status/<int:order_id>", methods=["POST"])
def admin_update_status(order_id):
    status = request.form.get("status")
    if status:
        db = get_db()
        db.execute("update orders set status = ? where id = ?", (status, order_id))
        db.commit()
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/produk/hapus/<product_id>", methods=["POST"])
def admin_hapus_produk(product_id):
    db = get_db()
    db.execute("update products set is_active = 0 where id = ?", (product_id,))
    db.commit()
    return redirect(url_for("admin_dashboard"))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# --- AI Chat API ---
@app.route("/api/ai-chat", methods=["POST"])
def api_ai_chat():
    data = request.get_json()
    question = data.get("question", "").strip() if data else ""
    
    if not question:
        return jsonify({"answer": "Silakan tulis pertanyaan tentang ikan 🐟"})
    
    if not GEMINI_API_KEY:
        return jsonify({"answer": "Mohon maaf, Gemini API belum dikonfigurasi. Admin perlu memasukkan GEMINI_API_KEY di server."})
    
    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash", 
            system_instruction=SYSTEM_INSTRUCTION
        )
        response = model.generate_content(question)
        answer = response.text
        # Safety: replace newlines with <br> for HTML rendering if Gemini didn't use <br>
        answer = answer.replace('\n', '<br>')
        return jsonify({"answer": answer})
    except Exception as e:
        print(f"Gemini AI Error: {e}")
        return jsonify({"answer": "Maaf, terjadi kesalahan saat menghubungi AI. Silakan coba lagi nanti."})


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)

