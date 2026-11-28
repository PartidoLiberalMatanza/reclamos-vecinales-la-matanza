import base64
import binascii
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import smtplib
import ssl
import time
import uuid
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from PIL import Image, ImageOps
from database import DATA, database, initialize

os.umask(0o077)
ROOT = Path(__file__).resolve().parent
SECRET = os.environ.get("RV_SECRET", "")
ADMIN = os.environ.get("RV_ADMIN_PASSWORD", "")
ORIGIN = os.environ.get("RV_ORIGIN", "http://127.0.0.1:8000")
DEMO = os.environ.get("RV_DEMO") == "1"
CONTACT_ENABLED = os.environ.get("RV_CONTACT_ENABLED") == "1"
PRIVACY = os.environ.get("RV_PRIVACY_TEXT", "").strip()
if len(SECRET) < 32 or len(ADMIN) < 16:
    raise RuntimeError("Configurá RV_SECRET (32 caracteres) y RV_ADMIN_PASSWORD (16 caracteres).")
if not DEMO and not ORIGIN.startswith("https://"):
    raise RuntimeError("Configurá RV_ORIGIN con HTTPS fuera del modo de pruebas.")
if DEMO and ORIGIN != "http://127.0.0.1:8000":
    raise RuntimeError("El modo de prueba solo se permite en http://127.0.0.1:8000.")

CATEGORIES = ('Inseguridad', 'Alumbrado público', 'Residuos y ambiente', 'Calles y pavimento',
              'Agua y cloacas', 'Inundaciones', 'Maltrato y protección animal', 'Salud pública',
              'Transporte', 'Educación', 'Otros')
LOCALITIES = ('20 de Junio', 'Aldo Bonzi', 'Ciudad Evita', 'González Catán', 'Gregorio de Laferrere',
              'Isidro Casanova', 'La Tablada', 'Lomas del Mirador', 'Rafael Castillo', 'Ramos Mejía',
              'San Justo', 'Tapiales', 'Villa Celina', 'Villa Luzuriaga', 'Villa Madero', 'Virrey del Pino')
STATUSES = ('Registrado', 'En revisión', 'Presentado', 'En trámite', 'Resuelto', 'Cerrado')
MAX_BODY = 17 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 16_000_000

class Problem(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message

def require(condition, message, status="400 Bad Request"):
    if not condition:
        raise Problem(status, message)

def digest(value):
    return hmac.new(SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()

def field(data, key, maximum, minimum=0):
    value = data.get(key, "")
    require(isinstance(value, str), f"Revisá el campo {key}.")
    value = value.strip()
    require(minimum <= len(value) <= maximum and not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value),
            f"Revisá el campo {key}.")
    return value

def email(data):
    value = field(data, "email", 180).casefold()
    require(re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}", value),
            "Ingresá un correo electrónico válido.")
    return value

def body(env):
    require(env.get("HTTP_ORIGIN") == ORIGIN, "Origen inválido.", "403 Forbidden")
    require(env.get("CONTENT_TYPE", "").split(";")[0] == "application/json", "Formato inválido.")
    try:
        length = int(env.get("CONTENT_LENGTH") or 0)
        require(0 < length <= MAX_BODY, "El envío supera el tamaño permitido.", "413 Payload Too Large")
        data = json.loads(env["wsgi.input"].read(length))
    except (ValueError, RecursionError):
        raise Problem("400 Bad Request", "Solicitud inválida.")
    require(isinstance(data, dict), "Solicitud inválida.")
    return data

def limit(key, amount, seconds=3600):
    now = int(time.time())
    period = now - now % seconds
    with database() as db:
        db.execute("DELETE FROM limits WHERE period < ?", (now - 86400,))
        count = db.execute(
            """INSERT INTO limits VALUES (?, ?, 1)
               ON CONFLICT(bucket,period) DO UPDATE SET count=count+1 RETURNING count""",
            (digest(key), period)).fetchone()[0]
    require(count <= amount, "Superaste el límite de envíos. Intentá más tarde.", "429 Too Many Requests")

def photo(value):
    require(isinstance(value, str) and len(value) <= 5_600_000, "Fotografía demasiado grande.")
    try:
        raw = base64.b64decode(value, validate=True)
        require(len(raw) <= 4 * 1024 * 1024, "Fotografía demasiado grande.")
        with Image.open(io.BytesIO(raw), formats=["JPEG", "PNG", "WEBP"]) as source:
            require(source.width * source.height <= Image.MAX_IMAGE_PIXELS, "Imagen demasiado grande.")
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((1600, 1600))
            image.info.clear()
            output = io.BytesIO()
            image.save(output, "JPEG", quality=85)
            return output.getvalue()
    except (ValueError, OSError, binascii.Error, Image.DecompressionBombError):
        raise Problem("400 Bad Request", "Usá fotografías JPG, PNG o WebP válidas.")

def submit_report(data):
    category = field(data, "category", 50)
    locality = field(data, "locality", 50)
    require(category in CATEGORIES and locality in LOCALITIES, "Elegí categoría y localidad.")
    require(data.get("consent") is True, "Confirmá las condiciones de envío.")
    place = field(data, "place", 180, 3)
    description = field(data, "description", 3000, 20)
    lat, lon = data.get("latitude"), data.get("longitude")
    require(type(lat) in (int, float) and type(lon) in (int, float)
            and -35.01 <= lat <= -34.60 and -59.00 <= lon <= -58.43,
            "Marcá una ubicación en la zona de La Matanza.")
    mode = data.get("mode")
    require(mode in ("anonymous", "identified"), "Elegí la modalidad del reclamo.")
    require(mode == "anonymous" or DEMO or PRIVACY, "El registro identificado todavía no está habilitado.",
            "503 Service Unavailable")
    name = field(data, "name", 100, 2) if mode == "identified" else None
    address = email(data) if mode == "identified" else None
    pictures = data.get("photos", [])
    require(isinstance(pictures, list) and len(pictures) <= 3, "Adjuntá hasta tres fotografías.")
    images = [photo(value) for value in pictures]
    report, key = uuid.uuid4().hex, secrets.token_urlsafe(24)
    with database() as db:
        db.execute("""INSERT INTO reports
            (id, created, category, locality, place, description, latitude, longitude, name, email, tracking)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (report, int(time.time()), category, locality, place, description, round(lat, 3), round(lon, 3),
             name, address, digest("tracking:" + key)))
        db.executemany("INSERT INTO photos VALUES (?,?,?)",
                       [(uuid.uuid4().hex, report, image) for image in images])
    return {"id": report, "key": key}

PUBLIC_COLUMNS = "id, created, category, locality, place, description, latitude, longitude, status"
COUNT_SUPPORTS = "(SELECT count(*) FROM supports WHERE report=reports.id) AS supports"

def public_report(db, row):
    report = dict(row)
    report["photos"] = [p["id"] for p in db.execute("SELECT id FROM photos WHERE report=?", (row["id"],))]
    return report

def send_code(address, code):
    if DEMO:
        mailbox = DATA / "demo-mail"
        mailbox.mkdir(exist_ok=True, mode=0o700)
        (mailbox / digest("mail:" + address)).write_text(code, encoding="utf-8")
        return
    host, sender = os.environ.get("RV_SMTP_HOST"), os.environ.get("RV_SMTP_FROM")
    require(host and sender and PRIVACY, "La verificación por correo todavía no está configurada.",
            "503 Service Unavailable")
    message = EmailMessage()
    message["To"], message["From"], message["Subject"] = address, sender, "Código para apoyar un reclamo"
    message.set_content(f"Tu código es {code}. Vence en 10 minutos.")
    try:
        with smtplib.SMTP_SSL(host, int(os.environ.get("RV_SMTP_PORT", "465")), timeout=10,
                              context=ssl.create_default_context()) as smtp:
            username = os.environ.get("RV_SMTP_USER")
            if username:
                smtp.login(username, os.environ.get("RV_SMTP_PASSWORD", ""))
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        raise Problem("503 Service Unavailable", "No se pudo enviar el correo.")

def challenge(address):
    now = int(time.time())
    code = f"{secrets.randbelow(1_000_000):06d}"
    token = digest(f"code:{address}:{code}")
    with database() as db:
        db.execute("DELETE FROM codes WHERE expires < ?", (now,))
        db.execute("""INSERT INTO codes VALUES (?,?,?,0)
            ON CONFLICT(email) DO UPDATE SET digest=excluded.digest, expires=excluded.expires, attempts=0""",
                   (digest("mail:" + address), token, now + 600))
    try:
        send_code(address, code)
    except Problem:
        with database() as db:
            db.execute("DELETE FROM codes WHERE digest=?", (token,))
        raise

def support(data, address):
    report, code = field(data, "id", 32, 32), field(data, "code", 6, 6)
    voter = digest("mail:" + address)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        record = db.execute("SELECT * FROM codes WHERE email=?", (voter,)).fetchone()
        require(record and record["expires"] >= time.time() and record["attempts"] < 5,
                "El código venció o agotó los intentos.")
        db.execute("UPDATE codes SET attempts=attempts+1 WHERE email=?", (voter,))
        verified = hmac.compare_digest(record["digest"], digest(f"code:{address}:{code}"))
        if verified:
            require(db.execute("SELECT 1 FROM reports WHERE id=? AND visibility='published'", (report,)).fetchone(),
                    "Reclamo no disponible.", "404 Not Found")
            db.execute("DELETE FROM codes WHERE email=?", (voter,))
            cursor = db.execute("INSERT INTO supports VALUES (?,?) ON CONFLICT DO NOTHING", (report, voter))
            return {"added": cursor.rowcount == 1}
    raise Problem("400 Bad Request", "El código es incorrecto.")

def session_token(env):
    from http.cookies import CookieError, SimpleCookie
    try:
        cookie = SimpleCookie(env.get("HTTP_COOKIE", "")).get("rv_admin")
        if cookie and re.fullmatch(r"[A-Za-z0-9_-]{43}", cookie.value):
            return digest("session:" + cookie.value)
    except CookieError:
        pass
    return ""

def is_admin(env):
    token = session_token(env)
    if not token:
        return False
    with database() as db:
        return bool(db.execute("SELECT 1 FROM admin_sessions WHERE token=? AND expires>?",
                               (token, int(time.time()))).fetchone())

def moderate(data):
    report = field(data, "id", 32, 32)
    visibility, status = data.get("visibility"), data.get("status")
    require(visibility in ("pending", "published", "hidden") and status in STATUSES, "Estado inválido.")
    ref, agency = field(data, "ref", 100), field(data, "agency", 120)
    require(bool(ref) == bool(agency), "Completá número y organismo para guardar un expediente.")
    place, description = field(data, "place", 180, 3), field(data, "description", 3000, 20)
    require(visibility != "published" or data.get("reviewed") is True, "Confirmá la revisión de datos personales.")
    selected = data.get("remove_photos", [])
    require(isinstance(selected, list) and len(selected) <= 3
            and all(isinstance(item, str) for item in selected), "Selección de fotos inválida.")
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT * FROM reports WHERE id=?", (report,)).fetchone()
        require(old, "Reclamo no encontrado.", "404 Not Found")
        db.execute("""UPDATE reports SET visibility=?, status=?, place=?, description=?,
            official_ref=?, official_agency=? WHERE id=?""", (visibility, status, place, description, ref, agency, report))
        db.executemany("DELETE FROM photos WHERE report=? AND id=?", [(report, item) for item in selected])
        if (status, ref, agency) != (old["status"], old["official_ref"], old["official_agency"]):
            db.execute("INSERT INTO updates VALUES (?,?,?,?,?,?)",
                       (uuid.uuid4().hex, report, int(time.time()), status, agency, ref))

def read_api(env, path):
    if path == "/api/config":
        return {"privacy": PRIVACY or ("Modo de pruebas. Usá datos ficticios." if DEMO else ""),
                "contact": bool(DEMO or (CONTACT_ENABLED and PRIVACY)),
                "verification": bool(DEMO or (PRIVACY and os.environ.get("RV_SMTP_HOST") and os.environ.get("RV_SMTP_FROM")))}
    with database() as db:
        if path == "/api/reports":
            filters = parse_qs(env.get("QUERY_STRING", ""))
            conditions = ["visibility='published'"]
            values = []
            for column, choices in (("category", CATEGORIES), ("locality", LOCALITIES)):
                selected = filters.get(column, [""])[0]
                if selected:
                    require(selected in choices, "Filtro inválido.")
                    conditions.append(f"{column}=?")
                    values.append(selected)
            where = " AND ".join(conditions)
            rows = db.execute(f"""SELECT {PUBLIC_COLUMNS}, {COUNT_SUPPORTS} FROM reports
                WHERE {where} ORDER BY created DESC, id DESC LIMIT 500""", values)
            return [public_report(db, row) for row in rows]
        if path.startswith("/api/reports/"):
            row = db.execute(f"""SELECT {PUBLIC_COLUMNS}, {COUNT_SUPPORTS} FROM reports
                WHERE id=? AND visibility='published'""", (path.rsplit("/", 1)[1],)).fetchone()
            require(row, "Reclamo no disponible.", "404 Not Found")
            return public_report(db, row)
        if path.startswith("/api/photos/"):
            photo_id = path.rsplit("/", 1)[1]
            row = db.execute("""SELECT image FROM photos JOIN reports ON photos.report=reports.id
                WHERE photos.id=? AND (reports.visibility='published' OR ?)""",
                (photo_id, is_admin(env))).fetchone()
            require(row, "Fotografía no disponible.", "404 Not Found")
            return ("image/jpeg", row["image"])
        if path == "/api/admin":
            require(is_admin(env), "Ingresá al panel privado.", "401 Unauthorized")
            return {"reports": [public_report(db, row) for row in db.execute(
                        """SELECT id, created, category, locality, place, description, name, email, visibility,
                               status, official_ref, official_agency FROM reports ORDER BY created DESC""")],
                    "contacts": [dict(row) for row in db.execute("SELECT * FROM contacts ORDER BY created DESC")]}
    raise Problem("404 Not Found", "Página no encontrada.")

def write_api(env, path, headers):
    ip = env.get("REMOTE_ADDR", "unknown")
    limit("requests:" + ip, 100)
    data = body(env)
    if path == "/api/reports":
        limit("report:" + ip, 8)
        return submit_report(data)
    if path == "/api/track":
        limit("track:" + ip, 40)
        with database() as db:
            report = field(data, "id", 32, 32)
            key = digest("tracking:" + field(data, "key", 80, 16))
            row = db.execute("""SELECT id, status, visibility, official_ref, official_agency FROM reports
                WHERE id=? AND tracking=?""", (report, key)).fetchone()
            require(row, "Código o clave de seguimiento inválidos.", "404 Not Found")
            result = dict(row)
            result["history"] = [dict(item) for item in db.execute(
                "SELECT created,status,agency,ref FROM updates WHERE report=? ORDER BY created DESC,id DESC", (report,))]
            return result
    if path == "/api/contact":
        require(DEMO or (CONTACT_ENABLED and PRIVACY), "La solicitud de contacto todavía no está habilitada.", "503 Service Unavailable")
        limit("contact:" + ip, 5)
        address, locality = email(data), field(data, "locality", 50)
        require(data.get("consent") is True and locality in LOCALITIES, "Confirmá el consentimiento y la localidad.")
        with database() as db:
            db.execute("INSERT INTO contacts VALUES (?,?,?,?,0)",
                       (uuid.uuid4().hex, int(time.time()), locality, address))
        return {}
    if path in ("/api/code", "/api/support"):
        address = email(data)
        if path == "/api/support":
            return support(data, address)
        limit("code-ip:" + ip, 12)
        limit("code-email:" + address, 3)
        challenge(address)
        return {}
    if path == "/api/admin/login":
        limit("login:" + ip, 8)
        require(hmac.compare_digest(field(data, "password", 300).encode(), ADMIN.encode()),
                "Clave incorrecta.", "401 Unauthorized")
        now = int(time.time())
        token = secrets.token_urlsafe(32)
        with database() as db:
            db.execute("DELETE FROM admin_sessions WHERE expires<=? OR token=?", (now, session_token(env)))
            db.execute("INSERT INTO admin_sessions VALUES (?,?)", (digest("session:" + token), now + 3600))
        cookie = f"rv_admin={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=3600"
        headers.append(("Set-Cookie", cookie + ("; Secure" if ORIGIN.startswith("https://") else "")))
        return {}
    if path.startswith("/api/admin/"):
        require(is_admin(env), "Ingresá al panel privado.", "401 Unauthorized")
        if path == "/api/admin/logout":
            with database() as db:
                db.execute("DELETE FROM admin_sessions WHERE token=?", (session_token(env),))
            cookie = "rv_admin=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
            headers.append(("Set-Cookie", cookie + ("; Secure" if ORIGIN.startswith("https://") else "")))
            return {}
        if path == "/api/admin/moderate":
            moderate(data)
            return {}
        if path == "/api/admin/redact":
            with database() as db:
                db.execute("UPDATE reports SET name=NULL, email=NULL WHERE id=?", (field(data, "id", 32, 32),))
            return {}
        if path == "/api/admin/contact":
            with database() as db:
                contact_id = field(data, "id", 32, 32)
                if data.get("delete") is True:
                    db.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
                else:
                    db.execute("UPDATE contacts SET handled=1 WHERE id=?", (contact_id,))
            return {}
    raise Problem("404 Not Found", "Página no encontrada.")

STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/community.js": ("community.js", "text/javascript; charset=utf-8"),
          "/vendor/leaflet/leaflet.js": ("vendor/leaflet/leaflet.js", "text/javascript; charset=utf-8"),
          "/vendor/leaflet/leaflet.css": ("vendor/leaflet/leaflet.css", "text/css; charset=utf-8")}

def application(env, start):
    headers = [("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
               ("X-Frame-Options", "DENY"), ("Referrer-Policy", "strict-origin-when-cross-origin"),
               ("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src https://fonts.gstatic.com; img-src 'self' blob: data: https:; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]
    status, mime = "200 OK", "application/json; charset=utf-8"
    path, method = env["PATH_INFO"], env["REQUEST_METHOD"]
    try:
        if method == "GET" and path in STATIC:
            filename, mime = STATIC[path]
            content = (ROOT / filename).read_bytes()
        else:
            require(method in ("GET", "POST"), "Método inválido.", "405 Method Not Allowed")
            result = read_api(env, path) if method == "GET" else write_api(env, path, headers)
            if isinstance(result, tuple):
                mime, content = result
            else:
                content = json.dumps(result, ensure_ascii=False).encode()
    except Problem as error:
        status = error.status
        content = json.dumps({"error": error.message}, ensure_ascii=False).encode()
    start(status, headers + [("Content-Type", mime), ("Content-Length", str(len(content)))])
    return [content]

initialize()

if __name__ == "__main__":
    with make_server("127.0.0.1", 8000, application) as server:
        print("Reclamos Vecinales · http://127.0.0.1:8000", flush=True)
        server.serve_forever()
