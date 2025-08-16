# car/routes.py
import os
from flask import Blueprint,jsonify, request, url_for, current_app, send_from_directory
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from .database import create_connection, sqlp, is_pg

bp = Blueprint("main", __name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def make_photo_url(value: str | None) -> str | None:
    """Turn a DB value (filename or S3 key/full URL) into a public URL."""
    if not value:
        return None
    v = str(value)
    if v.lower().startswith(("http://", "https://")):
        return v
    # serve from our uploads route; _external makes it absolute for the browser
    return url_for("main.uploaded_file", filename=v, _external=True)

@bp.route("/api/vehicles", methods=["GET"])
@login_required
def api_list_vehicles():
    conn = create_connection()
    cur = conn.cursor()
    try:
        cur.execute(sqlp("""
            SELECT v.id, v.marca, v.modelo, v.matricula, v.ano,
                   (SELECT vp.photo
                      FROM vehicle_photos vp
                     WHERE vp.vehicle_id = v.id
                     ORDER BY vp.id ASC
                     LIMIT 1) AS photo_key
            FROM vehicles v
            ORDER BY v.id DESC
        """))
        rows = cur.fetchall()

        items = []
        for r in rows:
            vid, marca, modelo, matricula, ano, photo_key = r

            # Try S3/MinIO first; else local uploads
            photo_url = None
            try:
                from .storage import using_s3, get_url
                if photo_key and using_s3():
                    photo_url = get_url(photo_key)
                else:
                    photo_url = make_photo_url(photo_key)
            except Exception:
                photo_url = make_photo_url(photo_key)

            items.append({
                "id": vid,
                "marca": marca,
                "modelo": modelo,
                "matricula": matricula,
                "ano": ano,
                "photo_url": photo_url
            })

        # consistent JSON shape
        return jsonify({"ok": True, "data": items}), 200
    finally:
        conn.close()

@bp.route("/api/vehicles", methods=["POST"])
@login_required
def api_create_vehicle():
    # aceita multipart/form-data (com fotos) ou application/json (sem fotos)
    marca = request.form.get("marca") or (request.json or {}).get("marca")
    modelo = request.form.get("modelo") or (request.json or {}).get("modelo")
    CC = request.form.get("CC") or (request.json or {}).get("CC")
    cor = request.form.get("cor") or (request.json or {}).get("cor")
    matricula = request.form.get("matricula") or (request.json or {}).get("matricula")
    ano = request.form.get("ano") or (request.json or {}).get("ano")
    num_lugares = request.form.get("num_lugares") or (request.json or {}).get("num_lugares")
    local_garagem = request.form.get("local_garagem") or (request.json or {}).get("local_garagem")
    estado_geral = request.form.get("estado_geral") or (request.json or {}).get("estado_geral")

    if not (marca and modelo and matricula):
        return jsonify({"error":"Campos obrigatórios: marca, modelo, matrícula."}), 400

    conn = create_connection()
    cur = conn.cursor()
    try:
        if is_pg():
            cur.execute(sqlp("""
                INSERT INTO vehicles (marca, modelo, CC, cor, matricula, ano, num_lugares, local_garagem, estado_geral)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
            """), (marca, modelo, CC, cor, matricula, ano, num_lugares, local_garagem, estado_geral))
            vehicle_id = cur.fetchone()[0]
        else:
            cur.execute(sqlp("""
                INSERT INTO vehicles (marca, modelo, CC, cor, matricula, ano, num_lugares, local_garagem, estado_geral)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """), (marca, modelo, CC, cor, matricula, ano, num_lugares, local_garagem, estado_geral))
            vehicle_id = cur.lastrowid

        # fotos (opcional)
        photos = request.files.getlist("photos")
        if photos:
            try:
                from .storage import using_s3, put_fileobj
            except Exception:
                using_s3 = lambda: False
                put_fileobj = None

            os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)
            for photo in photos:
                if photo and photo.filename and allowed_file(photo.filename):
                    filename = secure_filename(photo.filename)
                    if using_s3() and put_fileobj:
                        key = put_fileobj(photo.stream, prefix=f"vehicles/{vehicle_id}", filename=filename, content_type=photo.mimetype)
                        stored_value = key
                    else:
                        path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
                        photo.save(path)
                        stored_value = filename
                    cur.execute(sqlp("INSERT INTO vehicle_photos (vehicle_id, photo) VALUES (?, ?)"),
                                (vehicle_id, stored_value))

        conn.commit()
        return jsonify({"id": vehicle_id}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()

@bp.get("/api/vehicles/<int:vehicle_id>")
@login_required
def get_vehicle(vehicle_id: int):
    """Return one vehicle with its photos (JSON)."""
    conn = create_connection()
    cur = conn.cursor()
    try:
        # vehicle row (get whatever columns exist)
        cur.execute(sqlp("SELECT * FROM vehicles WHERE id = ?"), (vehicle_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"ok": False, "error": {"message": "Vehicle not found"}}), 404

        # turn row into dict by using cursor description
        cols = [c[0] for c in cur.description]
        vehicle = dict(zip(cols, row))

        # photos
        cur.execute(sqlp("SELECT photo FROM vehicle_photos WHERE vehicle_id = ? ORDER BY id ASC"), (vehicle_id,))
        photos = [r[0] for r in cur.fetchall()]
        vehicle["photos"] = photos

        return jsonify({"ok": True, "data": vehicle}), 200
    finally:
        conn.close()

@bp.get("/uploads/<path:filename>")
def uploaded_file(filename: str):
    """Serve uploaded files (so FE can render images)."""
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)