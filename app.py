import os
import uuid
import time
from flask import Flask, render_template, request, redirect, url_for, send_file
from werkzeug.utils import secure_filename
import secrets

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"stl"}

# Render free: stockage éphémère → on assume "preview temporaire"
MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
MAX_FILE_AGE_SECONDS = 60 * 60         # 1 heure (change si tu veux)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# ✅ SECRET_KEY via env (Render -> Environment -> SECRET_KEY)
# fallback local si tu veux
app.secret_key = os.environ.get("SECRET_KEY", "b14246d2abe25466743f12914fcff6f12d64937aed07220d60be99363e0ae55e")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def cleanup_uploads():
    """Supprime les fichiers trop anciens (utile sur Render free, évite l'accumulation)."""
    now = time.time()
    try:
        for name in os.listdir(UPLOAD_FOLDER):
            path = os.path.join(UPLOAD_FOLDER, name)
            if os.path.isfile(path):
                age = now - os.path.getmtime(path)
                if age > MAX_FILE_AGE_SECONDS:
                    os.remove(path)
    except Exception:
        # On ne casse pas l'app si le nettoyage échoue
        pass


@app.route("/", methods=["GET", "POST"])
def index():
    cleanup_uploads()

    if request.method == "POST":
        f = request.files.get("file")
        if not f or f.filename == "":
            return "Fichier manquant", 400

        if not allowed_file(f.filename):
            return "Format invalide (STL uniquement)", 400

        name = secure_filename(f.filename)
        newname = f"{uuid.uuid4().hex}_{name}"
        path = os.path.join(UPLOAD_FOLDER, newname)
        f.save(path)

        return redirect(url_for("view_stl", filename=newname))

    return render_template("index.html")


@app.route("/view/<filename>")
def view_stl(filename):
    # Sécurise le nom (évite chemins bizarres)
    safe = secure_filename(filename)
    path = os.path.join(UPLOAD_FOLDER, safe)
    if not os.path.isfile(path):
        return "Not found", 404

    file_url = url_for("stl_file", filename=safe)
    return render_template("view.html", file_url=file_url, filename=safe)


@app.route("/stl/<filename>")
def stl_file(filename):
    safe = secure_filename(filename)
    path = os.path.join(UPLOAD_FOLDER, safe)
    if not os.path.isfile(path):
        return "Not found", 404

    # mimetype STL courant
    return send_file(path, mimetype="application/sla", as_attachment=False)


if __name__ == "__main__":
    # Local uniquement. Sur Render: Start Command = gunicorn app:app
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
