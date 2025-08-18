# car/__init__.py
import os
from flask import Flask, jsonify, request
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from .database import create_tables, create_connection, sqlp, seed_admin_users
from .auth import auth_bp


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

    PROD = _is_prod()
    FE_PROXY = os.getenv("FE_PROXY", "1") == "1"  # 1 = Next FE proxies /api/* (recommended)

    # --- Core config ---
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-secret"),
        JSON_SORT_KEYS=False,
        PREFERRED_URL_SCHEME="https" if PROD else "http",
    )

    
    # Uploads: persist on Railway with a Volume mounted at /data
    default_upload = "/data/uploads" if PROD else os.path.join(os.getcwd(), "uploads")
    app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", default_upload)
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # Session cookies
    if FE_PROXY:
        # Same-site FE domain via Next proxy; no CORS needed
        app.config.update(
            SESSION_COOKIE_SAMESITE="Lax",
            SESSION_COOKIE_SECURE=PROD,     # True on Railway (HTTPS)
            SESSION_COOKIE_HTTPONLY=True,
        )
    else:
        # Cross-origin FE calling Flask directly; requires CORS + SameSite=None
        app.config.update(
            SESSION_COOKIE_SAMESITE="None",
            SESSION_COOKIE_SECURE=True,     # required with None
            SESSION_COOKIE_HTTPONLY=True,
        )

    # Respect X-Forwarded-* from Railway
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    # DB setup
    create_tables()

    seed_admin_users()

    # ---- CORS (only when NOT using FE proxy) ----
    if not FE_PROXY:
        from flask_cors import CORS
        frontend_origin = os.getenv("FRONTEND_URL", "http://localhost:3000")
        CORS(
            app,
            resources={r"/api/*": {"origins": [frontend_origin]}},
            supports_credentials=True,
            expose_headers=["Content-Type"],
        )

    # Auth manager (API style)
    login_manager = LoginManager()
    login_manager.login_view = None
    login_manager.init_app(app)

    @login_manager.user_loader
    def _load_user(user_id):
        # Optional: unify placeholders via sqlp()
        conn = create_connection()
        cur = conn.cursor()
        cur.execute(sqlp("SELECT id, username FROM users WHERE id = ?"), (user_id,))
        row = cur.fetchone()
        conn.close()
        return User(row[0], row[1]) if row else None

    @login_manager.unauthorized_handler
    def _unauthorized():
        return _err("Login required", 401)

    # Routes
    from .routes import bp
    app.register_blueprint(bp)
    app.register_blueprint(auth_bp)


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
