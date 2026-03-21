# car/routes.py
import os, io, zipfile
from flask import Blueprint,jsonify, request, url_for, current_app, send_from_directory,send_file
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from .database import create_connection, sqlp, is_pg, get_user_by_id, is_admin_user



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
    # query params
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except Exception:
        page = 1
    try:
        per_page = min(max(int(request.args.get("per_page", 10)), 1), 100)
    except Exception:
        per_page = 10

    q = (request.args.get("q") or "").strip()
    sort = (request.args.get("sort") or "id").lower()
    order = (request.args.get("order") or "desc").lower()
    allowed_sort = {"id", "marca", "modelo", "matricula", "ano"}
    if sort not in allowed_sort:
        sort = "id"
    if order not in {"asc", "desc"}:
        order = "desc"

    conn = create_connection()
    cur = conn.cursor()
    try:
        # WHERE (optional search)
        where = []
        params = []
        if q:
            where.append("(v.marca LIKE ? OR v.modelo LIKE ? OR v.matricula LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like, like])
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        # total
        cur.execute(sqlp(f"SELECT COUNT(*) FROM vehicles v {where_sql}"), tuple(params))
        total = int(cur.fetchone()[0])

        # page slice
        offset = (page - 1) * per_page

        # list query
        cur.execute(sqlp(f"""
            SELECT v.id, v.marca, v.modelo, v.matricula, v.ano,
                   (SELECT vp.photo
                      FROM vehicle_photos vp
                     WHERE vp.vehicle_id = v.id
                     ORDER BY vp.id ASC
                     LIMIT 1) AS photo_key
            FROM vehicles v
            {where_sql}
            ORDER BY v.{sort} {order.upper()}, v.id DESC
            LIMIT ? OFFSET ?
        """), tuple(params + [per_page, offset]))
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

        return jsonify({
            "ok": True,
            "data": items,
            "total": total,
            "page": page,
            "per_page": per_page
        }), 200
    finally:
        conn.close()


@bp.route("/api/vehicles/<int:vehicle_id>", methods=["DELETE"])
@login_required
def api_delete_vehicle(vehicle_id):
    conn = create_connection()
    cur = conn.cursor()
    try:
        # Remove photos first
        cur.execute(sqlp("DELETE FROM vehicle_photos WHERE vehicle_id = ?"), (vehicle_id,))
        # Remove the vehicle
        cur.execute(sqlp("DELETE FROM vehicles WHERE id = ?"), (vehicle_id,))
        conn.commit()
        return jsonify({"ok": True}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "error": {"message": str(e)}}), 400
    finally:
        conn.close()

@bp.route("/api/vehicles", methods=["POST"])
@login_required
def api_create_vehicle():
    # Accepts multipart/form-data (with photos) OR application/json (no photos)
    data = request.get_json(silent=True) or {}  # <-- safe, won't raise 415

    def pick(name: str):
        # Prefer form value (multipart), otherwise JSON value (if any)
        v = request.form.get(name)
        if v is None:
            v = data.get(name)
        return v

    def _num(v):
        if v in (None, "", "null"):
            return None
        try:
            return int(v)
        except Exception:
            return None

    marca         = pick("marca")
    modelo        = pick("modelo")
    CC            = _num(pick("CC"))
    cor           = pick("cor")
    matricula     = pick("matricula")
    ano           = _num(pick("ano"))
    num_lugares   = _num(pick("num_lugares"))
    local_garagem = pick("local_garagem")
    estado_geral  = pick("estado_geral")

    if not (marca and modelo and matricula):
        return jsonify({"message": "Campos obrigatórios: marca, modelo, matrícula."}), 400

    conn = create_connection()
    cur = conn.cursor()
    try:
        # Insert vehicle
        params = (marca, modelo, CC, cor, matricula, ano, num_lugares, local_garagem, estado_geral)
        if is_pg():
            cur.execute(sqlp("""
                INSERT INTO vehicles (marca, modelo, CC, cor, matricula, ano, num_lugares, local_garagem, estado_geral)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
            """), params)
            vehicle_id = cur.fetchone()[0]
        else:
            cur.execute(sqlp("""
                INSERT INTO vehicles (marca, modelo, CC, cor, matricula, ano, num_lugares, local_garagem, estado_geral)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """), params)
            vehicle_id = cur.lastrowid

        # Handle uploaded photos (only present for multipart/form-data)
        photos = request.files.getlist("photos") if request.files else []
        if photos:
            try:
                from .storage import using_s3, put_fileobj
            except Exception:
                using_s3 = lambda: False
                put_fileobj = None

            os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)

            for photo in photos:
                if not photo or not photo.filename:
                    continue
                if not allowed_file(photo.filename):
                    continue
                filename = secure_filename(photo.filename)
                if using_s3() and put_fileobj:
                    key = put_fileobj(
                        photo.stream,
                        prefix=f"vehicles/{vehicle_id}",
                        filename=filename,
                        content_type=photo.mimetype,
                    )
                    stored_value = key
                else:
                    path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
                    photo.save(path)
                    stored_value = filename

                cur.execute(
                    sqlp("INSERT INTO vehicle_photos (vehicle_id, photo) VALUES (?, ?)"),
                    (vehicle_id, stored_value),
                )

        conn.commit()

        # Return consistent shape
        return jsonify({"ok": True, "data": {"id": vehicle_id}}), 201

    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "error": {"message": str(e)}}), 400
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

def _num(v):
    if v in (None, "", "null"): return None
    try:
        return int(v)
    except Exception:
        return None


@bp.post("/api/vehicles/<int:vehicle_id>")
@login_required
def update_vehicle(vehicle_id: int):
    """
    Update a vehicle using POST + method override (_method=PUT or X-HTTP-Method-Override: PUT).
    Accepts multipart form with scalar fields, delete_photos[], and photos uploads.
    """
    method_override = (request.form.get("_method") or request.headers.get("X-HTTP-Method-Override") or "").upper()
    if method_override not in ("PUT", "PATCH"):
        return jsonify({"ok": False, "error": {"message": "Method Not Allowed"}}), 405

    conn = create_connection()
    cur = conn.cursor()
    try:
        # Ensure vehicle exists
        cur.execute(sqlp("SELECT id FROM vehicles WHERE id = ?"), (vehicle_id,))
        if not cur.fetchone():
            return jsonify({"ok": False, "error": {"message": "Vehicle not found"}}), 404

        # --- Update scalar fields (only those present) ---
        fields = {
            "marca": request.form.get("marca"),
            "modelo": request.form.get("modelo"),
            "matricula": request.form.get("matricula"),
            "ano": request.form.get("ano"),
            "CC": request.form.get("CC"),
            "num_lugares": request.form.get("num_lugares"),
            "cor": request.form.get("cor"),
            "estado_geral": request.form.get("estado_geral"),
            "local_garagem": request.form.get("local_garagem"),
        }

        # Build dynamic UPDATE for provided keys only
        set_parts, params = [], []
        for k, v in fields.items():
            if v is not None:
                if k in ("ano", "CC", "num_lugares"):
                    v = _num(v)
                set_parts.append(f"{k} = ?")
                params.append(v)
        if set_parts:
            params.append(vehicle_id)
            cur.execute(sqlp(f"UPDATE vehicles SET {', '.join(set_parts)} WHERE id = ?"), tuple(params))

        # --- Handle deletions ---
        # Accept both delete_photos and delete_photos[] for convenience
        to_delete = request.form.getlist("delete_photos") + request.form.getlist("delete_photos[]")
        if to_delete:
            # Remove from DB (where name matches)
            for name in to_delete:
                safe = os.path.basename(name)
                cur.execute(sqlp("DELETE FROM vehicle_photos WHERE vehicle_id = ? AND photo = ?"), (vehicle_id, safe))
                # Remove from disk if present
                path = os.path.join(current_app.config["UPLOAD_FOLDER"], safe)
                if os.path.isfile(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

        # --- Handle new uploads ---
        files = request.files.getlist("photos")
        for f in files:
            if not f or not f.filename:
                continue
            fname = secure_filename(f.filename)
            save_path = os.path.join(current_app.config["UPLOAD_FOLDER"], fname)
            # If you want to avoid collisions, prefix with vehicle_id or a uuid
            # from uuid import uuid4; fname = f"{vehicle_id}_{uuid4().hex}_{secure_filename(f.filename)}"
            f.save(save_path)
            cur.execute(sqlp("INSERT INTO vehicle_photos (vehicle_id, photo) VALUES (?, ?)"), (vehicle_id, fname))

        conn.commit()

        # Return the updated record (same shape as GET)
        # vehicle
        cur.execute(sqlp("SELECT * FROM vehicles WHERE id = ?"), (vehicle_id,))
        row = cur.fetchone()
        cols = [c[0] for c in cur.description]
        vehicle = dict(zip(cols, row))
        # photos
        cur.execute(sqlp("SELECT photo FROM vehicle_photos WHERE vehicle_id = ? ORDER BY id ASC"), (vehicle_id,))
        vehicle["photos"] = [r[0] for r in cur.fetchall()]

        return jsonify({"ok": True, "data": vehicle}), 200
    finally:
        conn.close()

@bp.get("/api/backup")  # protect with @login_required and your admin check
@login_required
def api_backup():
    u = get_user_by_id(int(current_user.id))
    if not is_admin_user(u):
        return jsonify({"ok": False, "error": {"message": "Forbidden"}}), 403

    db_path = os.getenv("DATABASE_URL","sqlite:///").split("sqlite:///",1)[1]
    up_dir = current_app.config["UPLOAD_FOLDER"]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if os.path.exists(db_path):
            z.write(db_path, arcname="app.db")
        for root, _, files in os.walk(up_dir):
            for f in files:
                p = os.path.join(root, f)
                arc = os.path.relpath(p, up_dir)
                z.write(p, arcname=f"uploads/{arc}")
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name="backup.zip")

@bp.get("/uploads/<path:filename>")
def uploaded_file(filename: str):
    """Serve uploaded files (so FE can render images)."""
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)


# ---- Standvirtual price tracker routes ----

@bp.get("/api/scraped-listings")
def api_scraped_listings():
    """
    Get all scraped car listings with optional filtering.
    Query params: ?brand=Toyota&model=Corolla&limit=50
    """
    try:
        brand = request.args.get("brand", "").strip()
        model = request.args.get("model", "").strip()
        limit = min(max(int(request.args.get("limit", 50)), 1), 500)
    except Exception:
        limit = 50
    
    conn = create_connection()
    cur = conn.cursor()
    try:
        query = "SELECT id, listing_id, brand, model, year, price, current_price, url, mileage FROM scraped_listings WHERE 1=1"
        params = []
        
        if brand:
            query += " AND brand ILIKE ?" if is_pg() else " AND brand LIKE ?"
            params.append(f"%{brand}%")
        if model:
            query += " AND model ILIKE ?" if is_pg() else " AND model LIKE ?"
            params.append(f"%{model}%")
        
        query += " ORDER BY current_price DESC LIMIT ?"
        params.append(limit)
        
        cur.execute(sqlp(query), params)
        rows = cur.fetchall()
        
        cols = [c[0] for c in cur.description] if cur.description else []
        listings = [dict(zip(cols, row)) for row in rows]
        
        return jsonify({"ok": True, "count": len(listings), "listings": listings}), 200
    finally:
        conn.close()


@bp.get("/api/scraped-listings/<listing_id>/history")
def api_listing_price_history(listing_id: str):
    """
    Get price history for a specific listing.
    Query params: ?limit=30
    """
    try:
        limit = min(max(int(request.args.get("limit", 30)), 1), 500)
    except Exception:
        limit = 30
    
    conn = create_connection()
    cur = conn.cursor()
    try:
        # Get listing info
        cur.execute(sqlp("SELECT id, listing_id, brand, model, year, url FROM scraped_listings WHERE listing_id = ?"), (listing_id,))
        listing = cur.fetchone()
        if not listing:
            return jsonify({"ok": False, "error": "Listing not found"}), 404
        
        listing_cols = [c[0] for c in cur.description]
        listing_data = dict(zip(listing_cols, listing))
        
        # Get price history (newest first, limit)
        cur.execute(sqlp("""
            SELECT price, recorded_at FROM listing_price_history 
            WHERE listing_id = ? 
            ORDER BY recorded_at DESC 
            LIMIT ?
        """), (listing_id, limit))
        
        history = cur.fetchall()
        history_cols = [c[0] for c in cur.description]
        history_data = [dict(zip(history_cols, row)) for row in history]
        history_data.reverse()  # Chronological order (oldest first)
        
        return jsonify({
            "ok": True,
            "listing": listing_data,
            "history": history_data
        }), 200
    finally:
        conn.close()


@bp.get("/api/scraped-listings/stats")
def api_scraped_stats():
    """
    Get scraper statistics (total listings, price records, last scrape).
    """
    conn = create_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM scraped_listings")
        total_listings = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM listing_price_history")
        total_history = cur.fetchone()[0]
        
        cur.execute(sqlp("SELECT MAX(scraped_at) FROM scraped_listings"))
        last_scrape = cur.fetchone()[0]
        
        return jsonify({
            "ok": True,
            "total_listings": total_listings,
            "total_price_records": total_history,
            "last_scrape": last_scrape
        }), 200
    finally:
        conn.close()

@bp.route("/api/photos/export", methods=["GET"])
@login_required
def export_photos():
    """Download all photos as ZIP."""
    uploads_dir = current_app.config["UPLOAD_FOLDER"]
    
    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for photo in os.listdir(uploads_dir):
            photo_path = os.path.join(uploads_dir, photo)
            if os.path.isfile(photo_path):
                zf.write(photo_path, arcname=photo)
    
    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='brandacars-photos.zip'
    )