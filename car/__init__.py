# car/__init__.py
import os
from flask import Flask, jsonify, request
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS

from .database import create_tables, create_connection, sqlp


def _is_prod():
    # Treat Railway or explicit ENV=prod as production
    return os.getenv("ENV", "").lower() == "prod" or bool(os.getenv("RAILWAY_STATIC_URL"))


class User(UserMixin):
    def __init__(self, id, username):
        self.id = str(id)
        self.username = username


def load_user_from_db(user_id):
    conn = create_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username FROM users WHERE id = %s" if os.getenv("DATABASE_URL")
        else "SELECT id, username FROM users WHERE id = ?",
        (user_id,)
    )
    row = cur.fetchone()
    conn.close()
    return User(row[0], row[1]) if row else None


def _ok(data=None, status=200):
    return jsonify({"ok": True, "data": data or {}}), status


def _err(message, status=400):
    return jsonify({"ok": False, "error": {"message": message}}), status


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", os.path.join(os.getcwd(), "uploads"))
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # Cookies for session (Flask-Login)
    PROD = _is_prod()
    app.config.update(
        SESSION_COOKIE_SAMESITE="None" if PROD else "Lax",
        SESSION_COOKIE_SECURE=PROD,  # must be True when SameSite=None on HTTPS (Railway)
        SESSION_COOKIE_HTTPONLY=True,
    )

    # DB setup
    create_tables()

    # ---- CORS (allow FE to send/receive cookies) ----
    # Set FRONTEND_URL in env (e.g., http://localhost:3000 or your Railway FE URL)
    frontend_origin = os.getenv("FRONTEND_URL", "http://localhost:3000")
    CORS(
        app,
        resources={r"/api/*": {"origins": [frontend_origin]}},
        supports_credentials=True,
        expose_headers=["Content-Type"],
    )

    # Auth manager (API style)
    login_manager = LoginManager()
    login_manager.login_view = None  # no HTML page redirects
    login_manager.init_app(app)

    @login_manager.user_loader
    def _load_user(user_id):
        return load_user_from_db(user_id)

    @login_manager.unauthorized_handler
    def _unauthorized():
        return _err("Login required", 401)

    # ---- Register your app routes (must use @login_required where needed) ----
    from .routes import bp
    app.register_blueprint(bp)

    # -------- AUTH API routes --------
    @app.route("/api/login", methods=["POST"])
    def api_login():
        data = request.get_json(silent=True) or request.form or {}
        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            return _err("username and password required", 400)

        conn = create_connection()
        cur = conn.cursor()
        cur.execute(sqlp("SELECT id, username, password_hash FROM users WHERE username = ?"), (username,))
        row = cur.fetchone()
        conn.close()

        if row and check_password_hash(row[2], password):
            login_user(User(row[0], row[1]))
            return _ok({"message": "Login successful"})
        return _err("Invalid credentials", 401)

    @app.route("/api/logout", methods=["POST"])
    @login_required
    def api_logout():
        logout_user()
        return _ok({"message": "Logged out"})

    @app.route("/api/seed-admin", methods=["POST", "GET"])
    def seed_admin():
        username = os.getenv("ADMIN_USER", "admin")
        password = os.getenv("ADMIN_PASS", "admin123")
        conn = create_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                sqlp("INSERT INTO users (username, password_hash) VALUES (?, ?)"),
                (username, generate_password_hash(password))
            )
            conn.commit()
            return _ok({"message": "Admin created"}, 201)
        except Exception:
            conn.rollback()
            return _ok({"message": "Admin already exists"}, 200)
        finally:
            conn.close()

    # ---- JSON error handlers (consistent shape) ----
    @app.errorhandler(404)
    def _404(_e):
        return _err("Not found", 404)

    @app.errorhandler(405)
    def _405(_e):
        return _err("Method not allowed", 405)

    @app.errorhandler(500)
    def _500(_e):
        return _err("Internal server error", 500)

    return app
