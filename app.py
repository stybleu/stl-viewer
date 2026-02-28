import os
import re
import uuid
import time
import json
import secrets
import unicodedata

from flask import (
    Flask, render_template, request, redirect, url_for, send_file, abort
)
from werkzeug.utils import secure_filename

# -----------------------
# Configuration
# -----------------------
UPLOAD_FOLDER = "uploads"
ROOMS_FILE = "rooms.json"   # metadata (nom affiché, date création, etc.)
ALLOWED_EXTENSIONS = {"stl"}

# Render free: stockage éphémère → on assume "preview temporaire"
MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
MAX_FILE_AGE_SECONDS = 600 * 60         # 10 heure (change si tu veux)

# Identifiant public de room dans l'URL (non secret)
ROOM_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,39}$")  # 3..40

# -----------------------
# Flask init
# -----------------------
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# ✅ SECRET_KEY via env (Render -> Environment -> SECRET_KEY)
# fallback local si tu veux
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "b14246d2abe25466743f12914fcff6f12d64937aed07220d60be99363e0ae55e"
)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# -----------------------
# Helpers
# -----------------------

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def slugify(name: str) -> str:
    """Convertit un nom de room en slug URL-friendly (public).
    Ex: 'Room Démo 01' -> 'room-demo-01'
    """
    name = (name or "").strip().lower()
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = re.sub(r"[^a-z0-9]+", "-", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name


def ensure_room_slug(room_slug: str) -> str:
    room_slug = (room_slug or "").strip()
    if not ROOM_SLUG_RE.match(room_slug):
        abort(404)
    return room_slug


def room_dir(room_slug: str) -> str:
    room_slug = ensure_room_slug(room_slug)
    path = os.path.join(UPLOAD_FOLDER, room_slug)
    os.makedirs(path, exist_ok=True)
    return path


def load_rooms() -> dict:
    """rooms.json -> dict {slug: {name, created_at}}"""
    try:
        with open(ROOMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_rooms(data: dict) -> None:
    try:
        with open(ROOMS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_room_display_name(room_slug: str) -> str:
    rooms = load_rooms()
    info = rooms.get(room_slug) or {}
    return (info.get("name") or room_slug).strip() or room_slug


def list_rooms() -> list:
    """Liste publique des rooms (dossiers dans uploads/ + metadata rooms.json)."""
    rooms_meta = load_rooms()
    out = []
    try:
        for entry in os.listdir(UPLOAD_FOLDER):
            d = os.path.join(UPLOAD_FOLDER, entry)
            if not os.path.isdir(d):
                continue
            slug = entry
            if not ROOM_SLUG_RE.match(slug):
                continue

            # compte fichiers STL
            count = 0
            newest = 0.0
            try:
                for fn in os.listdir(d):
                    p = os.path.join(d, fn)
                    if os.path.isfile(p):
                        count += 1
                        newest = max(newest, os.path.getmtime(p))
            except Exception:
                pass

            info = rooms_meta.get(slug) or {}
            created_at = float(info.get("created_at") or 0.0)
            name = (info.get("name") or slug).strip() or slug

            out.append({
                "slug": slug,
                "name": name,
                "count": count,
                "created_at": created_at,
                "newest": newest,
            })
    except Exception:
        return []

    # tri: plus récent d'abord (fichier le plus récent, sinon date de création)
    out.sort(key=lambda r: (r["newest"] or r["created_at"] or 0.0), reverse=True)
    return out


def unique_slug(base_slug: str) -> str:
    """Assure unicité du slug (room-demo, room-demo-2, ...)."""
    base_slug = ensure_room_slug(base_slug)
    rooms = load_rooms()

    if base_slug not in rooms and not os.path.isdir(os.path.join(UPLOAD_FOLDER, base_slug)):
        return base_slug

    # suffixe incrémental
    i = 2
    while True:
        candidate = f"{base_slug}-{i}"
        if len(candidate) > 40:
            # fallback : suffixe court aléatoire
            tail = secrets.token_hex(2)
            candidate = (base_slug[:35] + "-" + tail)[:40]
        if candidate not in rooms and not os.path.isdir(os.path.join(UPLOAD_FOLDER, candidate)):
            return candidate
        i += 1


def cleanup_uploads() -> None:
    """Supprime les fichiers trop anciens + rooms vides.
    Et nettoie rooms.json si des rooms disparaissent.
    """
    now = time.time()
    rooms_meta = load_rooms()
    changed_meta = False

    try:
        for entry in os.listdir(UPLOAD_FOLDER):
            base = os.path.join(UPLOAD_FOLDER, entry)

            if os.path.isfile(base):
                # compat vieux format: fichier à la racine
                age = now - os.path.getmtime(base)
                if age > MAX_FILE_AGE_SECONDS:
                    try:
                        os.remove(base)
                    except Exception:
                        pass
                continue

            if os.path.isdir(base):
                slug = entry
                # ne touche pas aux dossiers qui ne sont pas des rooms valides
                if not ROOM_SLUG_RE.match(slug):
                    continue

                # room
                try:
                    for name in os.listdir(base):
                        path = os.path.join(base, name)
                        if os.path.isfile(path):
                            age = now - os.path.getmtime(path)
                            if age > MAX_FILE_AGE_SECONDS:
                                try:
                                    os.remove(path)
                                except Exception:
                                    pass
                except Exception:
                    pass

                # supprime la room si vide
                try:
                    if not os.listdir(base):
                        try:
                            os.rmdir(base)
                        except OSError:
                            pass
                        if slug in rooms_meta:
                            rooms_meta.pop(slug, None)
                            changed_meta = True
                except Exception:
                    pass

        # supprime metadata orpheline (room supprimée manuellement)
        for slug in list(rooms_meta.keys()):
            if not os.path.isdir(os.path.join(UPLOAD_FOLDER, slug)):
                rooms_meta.pop(slug, None)
                changed_meta = True

    except Exception:
        # On ne casse pas l'app si le nettoyage échoue
        return

    if changed_meta:
        save_rooms(rooms_meta)


# -----------------------
# Routes
# -----------------------

@app.route("/", methods=["GET", "POST"])
def index():
    """Accueil : créer une room publique (nom) ou rejoindre une room existante.
    + liste des rooms créées en bas.
    """
    cleanup_uploads()

    error = None

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        if action == "create":
            room_name = (request.form.get("room_name") or "").strip()
            if len(room_name) < 2:
                error = "Nom de room trop court."
            else:
                base_slug = slugify(room_name)
                if not base_slug or len(base_slug) < 3:
                    error = "Nom invalide : utilise des lettres et chiffres."
                else:
                    # limite longueur (slug)
                    base_slug = base_slug[:40]
                    # force regex
                    if not ROOM_SLUG_RE.match(base_slug):
                        error = "Nom invalide : lettres/chiffres, 3 à 40 caractères (espaces OK)."
                    else:
                        slug = unique_slug(base_slug)
                        room_dir(slug)

                        rooms = load_rooms()
                        rooms[slug] = {
                            "name": room_name[:60],
                            "created_at": time.time(),
                        }
                        save_rooms(rooms)

                        return redirect(url_for("room", room_slug=slug))

        if action == "join":
            room_input = (request.form.get("room_slug") or "").strip()
            if not room_input:
                error = "Indique le nom (ou l'URL) de la room."
            else:
                # accepte /r/xxx, URL complète, ou juste le nom
                # on extrait le dernier segment
                room_input = room_input.strip()
                room_input = room_input.split("?")[0].split("#")[0].rstrip("/")
                if "/r/" in room_input:
                    room_input = room_input.split("/r/")[-1]
                else:
                    room_input = room_input.split("/")[-1]

                slug = slugify(room_input) or room_input.lower()
                slug = slug[:40]
                if not ROOM_SLUG_RE.match(slug):
                    error = "Room introuvable (nom invalide)."
                else:
                    if not os.path.isdir(os.path.join(UPLOAD_FOLDER, slug)):
                        error = "Cette room n'existe pas (ou a expiré)."
                    else:
                        return redirect(url_for("room", room_slug=slug))

    rooms = list_rooms()
    return render_template(
        "index.html",
        rooms=rooms,
        error=error,
        max_mb=int(MAX_CONTENT_LENGTH / (1024 * 1024)),
        max_age_minutes=int(MAX_FILE_AGE_SECONDS / 60),
    )


@app.route("/r/<room_slug>", methods=["GET", "POST"])
def room(room_slug):
    """Page d'une room : upload + liste des fichiers de la room."""
    cleanup_uploads()
    room_slug = ensure_room_slug(room_slug)
    folder = room_dir(room_slug)
    room_name = get_room_display_name(room_slug)

    if request.method == "POST":
        f = request.files.get("file")
        if not f or f.filename == "":
            return "Fichier manquant", 400

        if not allowed_file(f.filename):
            return "Format invalide (STL uniquement)", 400

        name = secure_filename(f.filename)
        newname = f"{uuid.uuid4().hex}_{name}"
        path = os.path.join(folder, newname)
        f.save(path)

        return redirect(url_for("view_stl", room_slug=room_slug, filename=newname))

    # liste fichiers
    files = []
    try:
        for fn in os.listdir(folder):
            p = os.path.join(folder, fn)
            if os.path.isfile(p):
                files.append({
                    "name": fn,
                    "mtime": os.path.getmtime(p),
                    "size": os.path.getsize(p),
                })
    except FileNotFoundError:
        files = []

    files.sort(key=lambda x: x["mtime"], reverse=True)

    return render_template(
        "room.html",
        room_slug=room_slug,
        room_name=room_name,
        files=files,
        max_mb=int(MAX_CONTENT_LENGTH / (1024 * 1024)),
        max_age_minutes=int(MAX_FILE_AGE_SECONDS / 60),
    )


@app.route("/r/<room_slug>/view/<filename>")
def view_stl(room_slug, filename):
    room_slug = ensure_room_slug(room_slug)

    safe = secure_filename(filename)
    path = os.path.join(room_dir(room_slug), safe)
    if not os.path.isfile(path):
        return "Not found", 404

    file_url = url_for("stl_file", room_slug=room_slug, filename=safe)
    room_name = get_room_display_name(room_slug)
    return render_template(
        "view.html",
        file_url=file_url,
        filename=safe,
        room_slug=room_slug,
        room_name=room_name,
    )


@app.route("/r/<room_slug>/stl/<filename>")
def stl_file(room_slug, filename):
    room_slug = ensure_room_slug(room_slug)

    safe = secure_filename(filename)
    path = os.path.join(room_dir(room_slug), safe)
    if not os.path.isfile(path):
        return "Not found", 404

    return send_file(path, mimetype="application/sla", as_attachment=False)


if __name__ == "__main__":
    # Local uniquement. Sur Render: Start Command = gunicorn app:app
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
