import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, send_file
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"stl"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "b14246d2abe25466743f12914fcff6f12d64937aed07220d60be99363e0ae55e")
app.config["MAX_CONTENT_LENGTH"] = 90 * 1024 * 1024  # 90MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/", methods=["GET", "POST"])
def index():
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
    file_url = url_for("stl_file", filename=filename)
    return render_template("view.html", file_url=file_url, filename=filename)


@app.route("/stl/<filename>")
def stl_file(filename):
    path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.isfile(path):
        return "Not found", 404
    return send_file(path, mimetype="application/sla", as_attachment=False)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
