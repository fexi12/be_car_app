# car/auth.py
from flask import Blueprint, jsonify, request
from flask_login import login_user, logout_user, login_required, UserMixin, current_user
from werkzeug.security import check_password_hash
from .database import create_connection, sqlp, get_user_by_username, get_user_by_id  # from the new database.py

auth_bp = Blueprint("auth", __name__, url_prefix="/api")


# Minimal user wrapper for Flask-Login (avoid storing password hash on the session)
class AuthUser(UserMixin):
    def __init__(self, id: int, username: str, role: str = "user"):
        # Flask-Login expects string ids
        self.id = str(id)
        self.username = username
        self.role = role


def _row_to_user(row):
    """
    Accepts rows from get_user_by_*:
      (id, username, password_hash, role)
    """
    if not row:
        return None
    return AuthUser(id=row[0], username=row[1], role=(row[3] if len(row) > 3 else "user"))


@auth_bp.post("/login")
def api_login():
    """
    Accepts JSON or form:
      { "username": "...", "password": "..." }
    Returns: { ok: true, data: { id, username, role } } or { ok: false, error: { message } }
    """
    data = request.get_json(silent=True) or request.form or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"ok": False, "error": {"message": "username and password required"}}), 400

    row = get_user_by_username(username) # (id, username, password_hash, role)
    if not row or not check_password_hash(row[2], password):
        return jsonify({"ok": False, "error": {"message": "Invalid credentials"}}), 401

    user = _row_to_user(row)
    login_user(user)
    return jsonify({"ok": True, "data": {"id": user.id, "username": user.username, "role": user.role}}), 200


@auth_bp.post("/logout")
@login_required
def api_logout():
    logout_user()
    return jsonify({"ok": True, "data": {"message": "Logged out"}}), 200

@auth_bp.get("/status")
def api_status():
    """
    Backward-compatible status endpoint.
    """
    return jsonify({
        "ok": True,
        "data": {
            "logged_in": bool(current_user.is_authenticated),
            "user": {
                "id": current_user.id if current_user.is_authenticated else None,
                "username": getattr(current_user, "username", None) if current_user.is_authenticated else None,
                "role": getattr(current_user, "role", "user") if current_user.is_authenticated else None,
            }
        }
    }), 200
