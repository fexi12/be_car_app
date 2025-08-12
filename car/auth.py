from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin
from werkzeug.security import check_password_hash, generate_password_hash
from .database import create_connection, is_pg

auth_bp = Blueprint("auth", __name__)

class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

def find_user_by_username(username):
    conn = create_connection()
    cur = conn.cursor()
    if is_pg():
        cur.execute("SELECT id, username, password_hash FROM users WHERE username=%s", (username,))
    else:
        cur.execute("SELECT id, username, password_hash FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    return User(*row) if row else None

def find_user_by_id(user_id):
    conn = create_connection()
    cur = conn.cursor()
    if is_pg():
        cur.execute("SELECT id, username, password_hash FROM users WHERE id=%s", (user_id,))
    else:
        cur.execute("SELECT id, username, password_hash FROM users WHERE id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return User(*row) if row else None

@auth_bp.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        if not username or not password:
            flash("Username and password required.")
            return redirect(url_for("auth.register"))
        if find_user_by_username(username):
            flash("Username already exists.")
            return redirect(url_for("auth.register"))
        conn = create_connection()
        cur = conn.cursor()
        if is_pg():
            cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                        (username, generate_password_hash(password)))
        else:
            cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                        (username, generate_password_hash(password)))
        conn.commit()
        conn.close()
        flash("Registered. Please log in.")
        return redirect(url_for("auth.login"))
    return render_template("register.html")

@auth_bp.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        user = find_user_by_username(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("index"))
        flash("Invalid credentials.")
    return render_template("login.html")

@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
