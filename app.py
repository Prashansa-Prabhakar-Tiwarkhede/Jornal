import os
import base64
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "diary-dev-secret-key-please-change")

# ── Cookie settings (critical for Render / HTTPS) ─────────────────────────────
app.config["SESSION_COOKIE_HTTPONLY"]  = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# On Render (HTTPS) set Secure=True automatically
if os.environ.get("RENDER"):
    app.config["SESSION_COOKIE_SECURE"] = True

# ── Database ──────────────────────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_URL   = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'diary.db')}")
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"]        = DB_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"]             = 5 * 1024 * 1024

db = SQLAlchemy(app)

# ── Models ────────────────────────────────────────────────────────────────────
class User(db.Model):
    __tablename__ = "users"
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(120), nullable=False)
    email         = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


class Entry(db.Model):
    __tablename__ = "entries"
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title      = db.Column(db.String(300), nullable=False)
    content    = db.Column(db.Text, nullable=False)
    mood       = db.Column(db.String(10), default="😊")
    image_data = db.Column(db.Text, nullable=True)
    entry_date = db.Column(db.String(10), nullable=False)   # YYYY-MM-DD
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_user(uid):
    return db.session.get(User, uid)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


# ── Pages ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("home"))
    return redirect(url_for("login_page"))


@app.route("/login")
def login_page():
    if "user_id" in session:
        return redirect(url_for("home"))
    return render_template("index.html", page="login")


@app.route("/register")
def register_page():
    if "user_id" in session:
        return redirect(url_for("home"))
    return render_template("index.html", page="register")


@app.route("/home")
@login_required
def home():
    user = get_user(session["user_id"])
    if not user:
        session.clear()
        return redirect(url_for("login_page"))
    return render_template("index.html", page="home", user=user)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


# ── Auth API ──────────────────────────────────────────────────────────────────
@app.route("/api/register", methods=["POST"])
def api_register():
    data  = request.get_json(force=True, silent=True) or {}
    name  = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    pw    = data.get("password") or ""

    if not name or not email or not pw:
        return jsonify({"error": "All fields are required"}), 400
    if len(pw) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered. Please sign in."}), 400

    u = User(name=name, email=email)
    u.set_password(pw)
    db.session.add(u)
    db.session.commit()
    session.permanent = True
    session["user_id"]   = u.id
    session["user_name"] = u.name
    return jsonify({"ok": True, "name": u.name})


@app.route("/api/login", methods=["POST"])
def api_login():
    data  = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    pw    = data.get("password") or ""

    if not email or not pw:
        return jsonify({"error": "Email and password are required"}), 400

    u = User.query.filter_by(email=email).first()
    if not u or not u.check_password(pw):
        return jsonify({"error": "Incorrect email or password"}), 401

    session.permanent = True
    session["user_id"]   = u.id
    session["user_name"] = u.name
    return jsonify({"ok": True, "name": u.name})


# ── Entries API ───────────────────────────────────────────────────────────────
@app.route("/api/entries", methods=["GET"])
@login_required
def api_get_entries():
    rows = Entry.query.filter_by(user_id=session["user_id"])\
                      .order_by(Entry.entry_date.desc(), Entry.created_at.desc()).all()
    return jsonify([{
        "id":         e.id,
        "title":      e.title,
        "content":    e.content,
        "mood":       e.mood,
        "image_data": e.image_data,
        "entry_date": e.entry_date,
        "created_at": e.created_at.strftime("%Y-%m-%d %H:%M")
    } for e in rows])


@app.route("/api/entries", methods=["POST"])
@login_required
def api_add_entry():
    title      = (request.form.get("title") or "").strip()
    content    = (request.form.get("content") or "").strip()
    mood       = request.form.get("mood") or "😊"
    entry_date = request.form.get("entry_date") or datetime.utcnow().strftime("%Y-%m-%d")

    if not title or not content:
        return jsonify({"error": "Title and content are required"}), 400

    image_data = None
    img = request.files.get("image")
    if img and img.filename:
        raw        = img.read()
        mime       = img.content_type or "image/jpeg"
        image_data = f"data:{mime};base64," + base64.b64encode(raw).decode()

    e = Entry(user_id=session["user_id"], title=title, content=content,
              mood=mood, image_data=image_data, entry_date=entry_date)
    db.session.add(e)
    db.session.commit()
    return jsonify({"ok": True, "id": e.id})


@app.route("/api/entries/<int:eid>", methods=["DELETE"])
@login_required
def api_delete_entry(eid):
    e = db.session.get(Entry, eid)
    if not e or e.user_id != session["user_id"]:
        return jsonify({"error": "Not found"}), 404
    db.session.delete(e)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/entries/<int:eid>", methods=["PUT"])
@login_required
def api_edit_entry(eid):
    e = db.session.get(Entry, eid)
    if not e or e.user_id != session["user_id"]:
        return jsonify({"error": "Not found"}), 404
    title   = (request.form.get("title") or "").strip()
    content = (request.form.get("content") or "").strip()
    mood    = request.form.get("mood") or e.mood
    if not title or not content:
        return jsonify({"error": "Title and content required"}), 400
    e.title   = title
    e.content = content
    e.mood    = mood
    img = request.files.get("image")
    if img and img.filename:
        raw          = img.read()
        mime         = img.content_type or "image/jpeg"
        e.image_data = f"data:{mime};base64," + base64.b64encode(raw).decode()
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/calendar")
@login_required
def api_calendar():
    rows = Entry.query.filter_by(user_id=session["user_id"]).all()
    cal  = {}
    for e in rows:
        cal[e.entry_date] = cal.get(e.entry_date, 0) + 1
    return jsonify(cal)


@app.route("/api/me")
@login_required
def api_me():
    u = get_user(session["user_id"])
    if not u:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"name": u.name, "email": u.email})


# ── Boot ──────────────────────────────────────────────────────────────────────
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
