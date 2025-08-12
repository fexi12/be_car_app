# car/__init__.py
import os
from flask import Flask
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
from .database import create_tables, create_connection

class User(UserMixin):
    def __init__(self, id, username):
        self.id = str(id)
        self.username = username

def load_user_from_db(user_id):
    conn = create_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE id = %s" if os.getenv("DATABASE_URL") else "SELECT id, username FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return User(row[0], row[1]) if row else None

def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    app.config["UPLOAD_FOLDER"] = os.path.join(os.getcwd(), "uploads")
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB

    # DB setup
    create_tables()

    # Auth
    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return load_user_from_db(user_id)

    # rotas “principais”
    from .routes import bp
    app.register_blueprint(bp)

    # rotas muito simples de auth (podes trocar por algo mais completo)
    from flask import request, render_template, redirect, url_for, flash
    from werkzeug.security import generate_password_hash, check_password_hash
    from .database import sqlp

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username")
            password = request.form.get("password")
            conn = create_connection()
            cur = conn.cursor()
            cur.execute(sqlp("SELECT id, username, password_hash FROM users WHERE username = ?"), (username,))
            row = cur.fetchone()
            conn.close()
            if row and check_password_hash(row[2], password):
                from flask_login import login_user
                login_user(User(row[0], row[1]))
                return redirect(url_for("main.index"))
            flash("Credenciais inválidas.", "error")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        from flask_login import logout_user
        logout_user()
        return redirect(url_for("login"))

    @app.route("/seed-admin")
    def seed_admin():
        # cria um utilizador admin simples (apenas para setup)
        username = os.getenv("ADMIN_USER", "admin")
        password = os.getenv("ADMIN_PASS", "admin123")
        conn = create_connection()
        cur = conn.cursor()
        try:
            cur.execute(sqlp("INSERT INTO users (username, password_hash) VALUES (?, ?)"),
                        (username, generate_password_hash(password)))
            conn.commit()
            return "Admin criado."
        except Exception:
            conn.rollback()
            return "Admin já existe."
        finally:
            conn.close()

    return app
