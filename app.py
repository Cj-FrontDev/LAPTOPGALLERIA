"""
Laptop Galleria - Flask single-file e-commerce app with DB, uploads, stock, and Messenger checkout.

How to run locally:
1. python -m venv venv
2. source venv/bin/activate   (mac/linux)  OR  venv\Scripts\activate (Windows)
3. pip install -r requirements.txt
4. export FLASK_APP=app.py
   export FLASK_ENV=development   (optional)
   export SECRET_KEY='changeme-please-set-a-secure-one'
   export ADMIN_PASS='set-an-admin-password'
   export PAGE_USERNAME='your_facebook_page_username'   # used for messenger link
5. python app.py
6. Open http://127.0.0.1:5000

Notes:
- Uploaded images are stored in ./uploads
- For deployment (Render / Railway / Heroku): set the environment variables SECRET_KEY, ADMIN_PASS, PAGE_USERNAME there.
"""

import os
import uuid
from datetime import datetime
from io import BytesIO

from flask import (Flask, flash, redirect, render_template_string, request,
                   send_from_directory, session, url_for)
from flask_sqlalchemy import SQLAlchemy
from PIL import Image

# -------------------------
# Configuration
# -------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'store.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # 4 MB max upload
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")  # change in production
PAGE_USERNAME = os.environ.get("PAGE_USERNAME", "YOUR_PAGE_USERNAME")  # Facebook Page username used for messenger

db = SQLAlchemy(app)

# -------------------------
# Models
# -------------------------
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(200), nullable=False, unique=True)
    description = db.Column(db.Text)
    price_cents = db.Column(db.Integer, nullable=False)
    image_filename = db.Column(db.String(400))  # saved file name in uploads
    stock = db.Column(db.Integer, default=0)

    def price(self):
        return self.price_cents / 100.0

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    customer_name = db.Column(db.String(200))
    customer_address = db.Column(db.Text)
    items = db.Column(db.Text)  # simple text summary
    total_cents = db.Column(db.Integer)


# -------------------------
# Helpers
# -------------------------
def init_db():
    db.create_all()
    if Product.query.count() == 0:
        # seed sample products (stock counts included)
        samples = [
            Product(name="Lenovo IdeaPad", slug="lenovo-ideapad", description="Reliable everyday laptop.", price_cents=2500000, image_filename=None, stock=5),
            Product(name="Dell Latitude", slug="dell-latitude", description="Business-grade laptop.", price_cents=1800000, image_filename=None, stock=3),
            Product(name="Gaming PC", slug="gaming-pc", description="High-performance desktop for gaming.", price_cents=4500000, image_filename=None, stock=2),
            Product(name="Mechanical Keyboard", slug="mechanical-keyboard", description="RGB mechanical keyboard.", price_cents=250000, image_filename=None, stock=10),
            Product(name="Gaming Mouse", slug="gaming-mouse", description="High DPI gaming mouse.", price_cents=120000, image_filename=None, stock=15),
        ]
        db.session.bulk_save_objects(samples)
        db.session.commit()

def allowed_file(filename):
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext in ("jpg", "jpeg", "png", "webp")

def save_and_resize_image(file_storage, output_size=(600,400)):
    """
    Save uploaded image to uploads folder and resize to fit output_size.
    Returns filename saved (unique).
    """
    filename = file_storage.filename
    if not allowed_file(filename):
        return None

    ext = filename.rsplit(".",1)[-1].lower()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(app.config["UPLOAD_FOLDER"], unique_name)

    # open with PIL and resize while preserving aspect ratio, then cover-crop
    im = Image.open(file_storage.stream).convert("RGB")
    # compute cover resize
    target_w, target_h = output_size
    im_ratio = im.width / im.height
    target_ratio = target_w / target_h

    if im_ratio > target_ratio:
        # image is wider -> resize by height then crop sides
        new_height = target_h
        new_width = int(im.width * (target_h / im.height))
    else:
        # image is taller -> resize by width then crop top/bottom
        new_width = target_w
        new_height = int(im.height * (target_w / im.width))

    im_resized = im.resize((new_width, new_height), Image.LANCZOS)

    # center-crop to target size
    left = (new_width - target_w) / 2
    top = (new_height - target_h) / 2
    right = left + target_w
    bottom = top + target_h
    im_cropped = im_resized.crop((left, top, right, bottom))

    # Save optimized JPEG
    im_cropped.save(path, format="JPEG", quality=85, optimize=True)
    return unique_name

def cart_get():
    return session.get("cart", {})  # {product_id: qty}

def cart_set(cart):
    session["cart"] = cart
    session.modified = True

def cart_total_cents(cart):
    total = 0
    for pid, qty in cart.items():
        p = Product.query.get(int(pid))
        if p:
            total += p.price_cents * qty
    return total

# -------------------------
# Templates (render_template_string to keep single-file)
# -------------------------
base_tpl = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{{ title or 'Laptop Galleria' }}</title>
  <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&display=swap" rel="stylesheet">
  <link href="https://unpkg.com/aos@2.3.1/dist/aos.css" rel="stylesheet">
  <style>
    :root {
      --violet:#9D00FF;
      --cyan:#00FFFF;
      --pink:#FF00AA;
      --dark:#0A0A0A;
      --card:#1E1E2F;
    }
    *{box-sizing:border-box}
    body {
      font-family:'Orbitron',sans-serif;
      background:var(--dark);
      color:#fff;
      margin:0;
      padding:16px;
      overflow-x:hidden;
    }
    header {
      text-align:center;
      padding:24px 0;
      background:radial-gradient(circle at top,var(--card),var(--dark));
      box-shadow:0 0 30px var(--violet);
      border-radius:12px;
      margin-bottom:24px;
      animation:fadeInDown 1s ease;
    }
    header h1 {
      font-size:2.3rem;
      color:var(--violet);
      text-shadow:0 0 20px var(--violet),0 0 40px var(--cyan);
      animation:glow 3s ease-in-out infinite alternate;
    }
    @keyframes glow {
      from { text-shadow:0 0 10px var(--violet); }
      to { text-shadow:0 0 30px var(--cyan),0 0 60px var(--violet); }
    }
    @keyframes fadeInDown {
      from {opacity:0; transform:translateY(-30px);}
      to {opacity:1; transform:translateY(0);}
    }
    .container{max-width:1100px;margin:0 auto;}
    nav{display:flex;gap:14px;justify-content:center;margin-bottom:12px;font-size:1.1em;}
    a{color:var(--cyan);text-decoration:none;transition:color .3s;}
    a:hover{color:var(--pink);}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;}
    .card{
      background:var(--card);
      border:2px solid var(--violet);
      padding:14px;
      border-radius:14px;
      text-align:center;
      box-shadow:0 0 20px rgba(157,0,255,0.4);
      transition:transform .3s, box-shadow .3s;
    }
    .card:hover{
      transform:translateY(-10px) scale(1.03);
      box-shadow:0 0 40px var(--violet);
    }
    img{width:100%;height:180px;object-fit:cover;border-radius:8px;border-bottom:3px solid var(--violet);}
    button{
      background:linear-gradient(90deg,var(--violet),var(--cyan));
      border:none;color:#000;padding:10px 16px;border-radius:8px;
      font-weight:bold;cursor:pointer;transition:all .3s;
    }
    button:hover{
      background:linear-gradient(90deg,var(--cyan),var(--pink));
      box-shadow:0 0 20px var(--violet);
      transform:scale(1.05);
    }
    .muted{color:#bbb;font-size:.95em;}
    form input,form textarea{
      width:100%;padding:10px;margin:6px 0;border-radius:6px;
      border:1px solid #333;background:#0d0d0d;color:#fff;
    }
    table{width:100%;border-collapse:collapse;margin-top:16px;}
    th,td{padding:8px;border-bottom:1px solid #333;}
    th{color:var(--cyan);}
  </style>
</head>
<body>
  <header data-aos="fade-down">
    <h1>⚡ Laptop Galleria ⚡</h1>
    <p class="muted">Your trusted shop for laptops & computer accessories</p>
  </header>
  <div class="container" data-aos="fade-up">
    <nav>
      <a href="{{ url_for('index') }}">Shop</a> |
      <a href="{{ url_for('view_cart') }}">Cart ({{ cart_count }})</a> |
      <a href="{{ url_for('admin') }}">Admin</a>
    </nav>
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <div style="background:#063;padding:8px;border-radius:6px;margin-bottom:12px">
          {% for m in messages %}<div>{{ m }}</div>{% endfor %}
        </div>
      {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
  </div>
  <script src="https://unpkg.com/aos@2.3.1/dist/aos.js"></script>
  <script>AOS.init({duration:1000});</script>
</body>
</html>
"""

index_tpl = """
{% extends 'base' %}
{% block content %}
  <h2>Featured Products</h2>
  <div class="grid">
    {% for p in products %}
      <div class="card">
        <a href="{{ url_for('product', slug=p.slug) }}">
          {% if p.image_filename %}
            <img src="{{ url_for('uploaded_file', filename=p.image_filename) }}" alt="{{ p.name }}">
          {% else %}
            <img src="{{ url_for('static_placeholder') }}" alt="placeholder">
          {% endif %}
        </a>
        <h3 style="color:#0ff">{{ p.name }}</h3>
        <div class="muted">₱{{ '%.2f'|format(p.price()/100) }}</div>
        <p class="muted">Stock: {{ p.stock }}</p>
        <p>{{ p.description or '' }}</p>
        <form action="{{ url_for('add_to_cart', product_id=p.id) }}" method="post" style="display:inline-block">
          <input type="hidden" name="qty" value="1">
          <button {% if p.stock < 1 %}disabled{% endif %}>Add to Cart</button>
        </form>
      </div>
    {% endfor %}
  </div>
{% endblock %}
"""

product_tpl = """
{% extends 'base' %}
{% block content %}
  <a href="{{ url_for('index') }}">← Back to shop</a>
  <div style="display:flex; gap:16px; margin-top:12px; flex-wrap:wrap">
    <div style="flex:1; min-width:260px">
      {% if product.image_filename %}
        <img src="{{ url_for('uploaded_file', filename=product.image_filename) }}" alt="{{ product.name }}">
      {% else %}
        <img src="{{ url_for('static_placeholder') }}" alt="placeholder">
      {% endif %}
    </div>
    <div style="flex:1; min-width:260px">
      <h2 style="color:#0ff">{{ product.name }}</h2>
      <div class="muted">₱{{ '%.2f'|format(product.price()/100) }}</div>
      <p>{{ product.description }}</p>
      <p class="muted">Stock: {{ product.stock }}</p>
      <form action="{{ url_for('add_to_cart', product_id=product.id) }}" method="post">
        <label>Quantity: <input name="qty" type="number" value="1" min="1" max="{{ product.stock }}"></label><br><br>
        <button {% if product.stock < 1 %}disabled{% endif %}>Add to Cart</button>
      </form>
    </div>
  </div>
{% endblock %}
"""

cart_tpl = """
{% extends 'base' %}
{% block content %}
  <h2>Your Cart</h2>
  {% if items %}
    <table width="100%" style="border-collapse:collapse">
      <thead style="text-align:left"><tr><th>Product</th><th>Qty</th><th>Price</th><th>Total</th><th></th></tr></thead>
      <tbody>
        {% for it in items %}
          <tr>
            <td>{{ it.product.name }}</td>
            <td>{{ it.qty }}</td>
            <td>₱{{ '%.2f'|format(it.product.price()/100) }}</td>
            <td>₱{{ '%.2f'|format(it.total/100) }}</td>
            <td>
              <form action="{{ url_for('remove_from_cart', product_id=it.product.id) }}" method="post" style="display:inline">
                <button type="submit">Remove</button>
              </form>
            </td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
    <h3>Grand total: ₱{{ '%.2f'|format(total_cents/100) }}</h3>

    <h3>Checkout</h3>
    <form action="{{ url_for('checkout') }}" method="post">
      <input name="name" placeholder="Full name" required>
      <input name="address" placeholder="Delivery address" required>
      <button type="submit">Place Order & Send to Messenger</button>
    </form>
  {% else %}
    <p>Your cart is empty.</p>
  {% endif %}
{% endblock %}
"""

orders_tpl = """
{% extends 'base' %}
{% block content %}
  <h2>Orders</h2>
  {% if orders %}
    <ul>
      {% for o in orders %}
        <li>Order #{{ o.id }} — ₱{{ '%.2f'|format(o.total_cents/100) }} — {{ o.created_at.strftime('%Y-%m-%d %H:%M') }}<br>
            <small>{{ o.customer_name }} — {{ o.customer_address }}</small><br>
            <small>{{ o.items }}</small>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <p>No orders yet.</p>
  {% endif %}
{% endblock %}
"""

admin_login_tpl = """
{% extends 'base' %}
{% block content %}
  <h2>Admin Login</h2>
  <form method="post" action="{{ url_for('admin_login') }}">
    <input name="password" type="password" placeholder="Admin password" required>
    <button type="submit">Login</button>
  </form>
{% endblock %}
"""

admin_panel_tpl = """
{% extends 'base' %}
{% block content %}
  <h2>Admin Panel</h2>
  <p><a href="{{ url_for('admin_logout') }}">Logout</a> | <a href="{{ url_for('admin') }}?new=1">Add New Product</a></p>

  {% if new %}
    <h3>Add Product</h3>
    <form method="post" action="{{ url_for('admin_add') }}" enctype="multipart/form-data">
      <input name="name" placeholder="Name" required>
      <input name="slug" placeholder="slug (unique, e.g. lenovo-ideapad)" required>
      <textarea name="description" placeholder="Description"></textarea>
      <input name="price" placeholder="Price in PHP (e.g. 25000)" required>
      <input name="stock" placeholder="Stock (integer)" required>
      <label>Image: <input type="file" name="image" accept="image/*"></label>
      <button type="submit">Create</button>
    </form>
  {% endif %}

  <h3>Products</h3>
  <div class="grid">
    {% for p in products %}
      <div class="card">
        {% if p.image_filename %}
          <img src="{{ url_for('uploaded_file', filename=p.image_filename) }}">
        {% else %}
          <img src="{{ url_for('static_placeholder') }}">
        {% endif %}
        <h3 style="color:#0ff">{{ p.name }}</h3>
        <div class="muted">₱{{ '%.2f'|format(p.price()/100) }} — Stock: {{ p.stock }}</div>
        <p>{{ p.description }}</p>
        <form method="post" action="{{ url_for('admin_edit', product_id=p.id) }}" enctype="multipart/form-data">
          <input name="price" placeholder="Price in PHP" value="{{ '%.2f'|format(p.price()/100) }}">
          <input name="stock" placeholder="Stock" value="{{ p.stock }}">
          <label>Replace image: <input type="file" name="image" accept="image/*"></label>
          <button type="submit">Update</button>
        </form>
      </div>
    {% endfor %}
  </div>

  <h3>Orders</h3>
  <a href="{{ url_for('orders_admin') }}">View Orders</a>

{% endblock %}
"""

orders_admin_tpl = """
{% extends 'base' %}
{% block content %}
  <h2>All Orders</h2>
  <p><a href="{{ url_for('admin') }}">Back to Admin</a></p>
  {% if orders %}
    <ul>
      {% for o in orders %}
        <li>#{{ o.id }} — ₱{{ '%.2f'|format(o.total_cents/100) }} — {{ o.created_at }}<br>
          <small>{{ o.customer_name }} — {{ o.customer_address }}</small><br>
          <small>{{ o.items }}</small>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <p>No orders yet.</p>
  {% endif %}
{% endblock %}
"""

# Register templates in a dict loader so we can still use render_template_string with extends
from jinja2 import DictLoader
app.jinja_loader = DictLoader({
    'base': base_tpl,
    'index.html': index_tpl,
    'product.html': product_tpl,
    'cart.html': cart_tpl,
    'orders.html': orders_tpl,
    'admin_login.html': admin_login_tpl,
    'admin_panel.html': admin_panel_tpl,
    'orders_admin.html': orders_admin_tpl,
})

# -------------------------
# Routes
# -------------------------
@app.before_request
def setup_once():
    if not hasattr(app, 'db_initialized'):
        init_db()
        app.db_initialized = True


@app.context_processor
def inject_cart_count():
    cart = cart_get()
    count = sum(cart.values()) if cart else 0
    return dict(cart_count=count)

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# A simple placeholder static image route
@app.route('/_placeholder.png')
def static_placeholder():
    # returns a 600x400 PNG placeholder generated on the fly
    buf = BytesIO()
    img = Image.new('RGB', (600, 400), color=(30,30,30))
    img.save(buf, format='PNG')
    buf.seek(0)
    return app.response_class(buf.read(), mimetype='image/png')

@app.route('/')
def index():
    products = Product.query.order_by(Product.id).all()
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'index.html')[0], products=products)

@app.route('/product/<slug>')
def product(slug):
    p = Product.query.filter_by(slug=slug).first_or_404()
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'product.html')[0], product=p)

@app.route('/add_to_cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    qty = int(request.form.get('qty', 1))
    p = Product.query.get_or_404(product_id)
    if p.stock < qty:
        flash("Not enough stock for that product.")
        return redirect(request.referrer or url_for('index'))
    cart = cart_get()
    cart[str(product_id)] = cart.get(str(product_id), 0) + qty
    cart_set(cart)
    flash("Added to cart")
    return redirect(request.referrer or url_for('index'))

@app.route('/remove_from_cart/<int:product_id>', methods=['POST'])
def remove_from_cart(product_id):
    cart = cart_get()
    cart.pop(str(product_id), None)
    cart_set(cart)
    flash("Removed from cart")
    return redirect(url_for('view_cart'))

@app.route('/cart')
def view_cart():
    cart = cart_get()
    items = []
    for pid, qty in cart.items():
        p = Product.query.get(int(pid))
        if p:
            items.append(type('X', (), {'product': p, 'qty': qty, 'total': p.price_cents * qty}))
    total = cart_total_cents(cart)
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'cart.html')[0], items=items, total_cents=total)

@app.route('/checkout', methods=['POST'])
def checkout():
    cart = cart_get()
    if not cart:
        flash("Cart is empty")
        return redirect(url_for('view_cart'))
    name = request.form.get('name')
    address = request.form.get('address')
    # Verify stock again and decrement
    items_summary = []
    total = 0
    for pid, qty in cart.items():
        p = Product.query.get(int(pid))
        if not p:
            flash("Product missing")
            return redirect(url_for('view_cart'))
        if p.stock < qty:
            flash(f"Not enough stock for {p.name}. Available: {p.stock}")
            return redirect(url_for('view_cart'))
        items_summary.append(f"{p.name} x{qty} @ ₱{p.price():.2f}")
        total += p.price_cents * qty

    # Decrement stock
    for pid, qty in cart.items():
        p = Product.query.get(int(pid))
        p.stock = max(p.stock - qty, 0)
    # create order
    order = Order(customer_name=name, customer_address=address, items="; ".join(items_summary), total_cents=total)
    db.session.add(order)
    db.session.commit()

    # empty cart
    cart_set({})

    # Prepare messenger redirect (prefill message)
    order_text = f"Laptop Galleria Order%0AOrder#: {order.id}%0A"
    for line in items_summary:
        order_text += f"- {line}%0A"
    order_text += f"%0ATotal: ₱{total/100:.2f}%0AName: {name}%0AAddress: {address}"

    messenger_url = f"https://m.me/{PAGE_USERNAME}?text={order_text}"
    # redirect user to messenger to complete arranging delivery
    return redirect(messenger_url)

# -------------------------
# Admin (very simple password based)
# -------------------------
@app.route('/admin', methods=['GET'])
def admin():
    if not session.get('admin'):
        return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'admin_login.html')[0])
    products = Product.query.order_by(Product.id).all()
    new = bool(request.args.get('new'))
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'admin_panel.html')[0], products=products, new=new)

@app.route('/admin/login', methods=['POST'])
def admin_login():
    pw = request.form.get('password')
    if pw == ADMIN_PASS:
        session['admin'] = True
        flash("Logged in as admin")
        return redirect(url_for('admin'))
    flash("Wrong password")
    return redirect(url_for('admin'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    flash("Logged out")
    return redirect(url_for('index'))

@app.route('/admin/add', methods=['POST'])
def admin_add():
    if not session.get('admin'):
        return redirect(url_for('admin'))
    name = request.form.get('name')
    slug = request.form.get('slug')
    description = request.form.get('description')
    price_php = float(request.form.get('price', '0') or 0)
    stock = int(request.form.get('stock', '0') or 0)
    img = request.files.get('image')
    filename = None
    if img and img.filename:
        filename = save_and_resize_image(img, output_size=(600,400))
    product = Product(name=name, slug=slug, description=description, price_cents=int(price_php*100), image_filename=filename, stock=stock)
    db.session.add(product)
    try:
        db.session.commit()
        flash("Product created")
    except Exception as e:
        db.session.rollback()
        flash("Error creating product: " + str(e))
    return redirect(url_for('admin'))

@app.route('/admin/edit/<int:product_id>', methods=['POST'])
def admin_edit(product_id):
    if not session.get('admin'):
        return redirect(url_for('admin'))
    p = Product.query.get_or_404(product_id)
    price_in = request.form.get('price')
    stock_in = request.form.get('stock')
    try:
        if price_in:
            # price form is in PHP like 25000.00
            p.price_cents = int(float(price_in) * 100)
        if stock_in is not None:
            p.stock = int(stock_in)
    except ValueError:
        flash("Invalid price or stock")
        return redirect(url_for('admin'))

    img = request.files.get('image')
    if img and img.filename:
        filename = save_and_resize_image(img, output_size=(600,400))
        if filename:
            # delete old image file if exists
            try:
                if p.image_filename:
                    oldpath = os.path.join(app.config['UPLOAD_FOLDER'], p.image_filename)
                    if os.path.exists(oldpath):
                        os.remove(oldpath)
            except Exception:
                pass
            p.image_filename = filename

    db.session.commit()
    flash("Product updated")
    return redirect(url_for('admin'))

@app.route('/admin/orders')
def orders_admin():
    if not session.get('admin'):
        return redirect(url_for('admin'))
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template_string(app.jinja_loader.get_source(app.jinja_env, 'orders_admin.html')[0], orders=orders)

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
