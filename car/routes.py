# car/routes.py
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_from_directory
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from .database import create_connection, sqlp, is_pg

bp = Blueprint("main", __name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@bp.route("/")
@login_required
def index():
    conn = create_connection()
    cur = conn.cursor()
    # lista veículos + uma foto (se existir)
    cur.execute(sqlp("""
        SELECT v.id, v.marca, v.modelo, v.matricula, v.ano,
               (SELECT photo FROM vehicle_photos vp WHERE vp.vehicle_id = v.id LIMIT 1) AS photo
        FROM vehicles v
        ORDER BY v.id DESC
    """))
    rows = cur.fetchall()
    conn.close()
    return render_template("index.html", vehicles=rows)

@bp.route("/add", methods=["GET", "POST"])
@login_required
def add_vehicle():
    if request.method == "POST":
        marca = request.form.get("marca")
        modelo = request.form.get("modelo")
        CC = request.form.get("CC")
        cor = request.form.get("cor")
        matricula = request.form.get("matricula")
        ano = request.form.get("ano")
        num_lugares = request.form.get("num_lugares")
        local_garagem = request.form.get("local_garagem")
        estado_geral = request.form.get("estado_geral")

        # validação mínima
        if not (marca and modelo and matricula):
            flash("Campos obrigatórios: marca, modelo, matrícula.", "error")
            return redirect(url_for("main.add_vehicle"))

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

            # fotos
            photos = request.files.getlist("photos")
            os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)
            for photo in photos:
                if photo and photo.filename and allowed_file(photo.filename):
                    filename = secure_filename(photo.filename)
                    file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
                    photo.save(file_path)
                    cur.execute(sqlp("INSERT INTO vehicle_photos (vehicle_id, photo) VALUES (?, ?)"),
                                (vehicle_id, filename))

            conn.commit()
            flash("Veículo criado com sucesso.", "success")
            return redirect(url_for("main.index"))
        except Exception as e:
            conn.rollback()
            # erro de unicidade de matrícula é o mais comum
            flash(f"Erro ao criar veículo: {str(e)}", "error")
            return redirect(url_for("main.add_vehicle"))
        finally:
            conn.close()

    return render_template("create_vehicle.html")

@bp.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    # apenas para ambiente local/demos. Em produção usa object storage.
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)
