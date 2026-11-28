"""WSGI entry point for a restricted HTTPS trial with a separate database."""
import base64
import hmac
import json
import os
import sys
from pathlib import Path

configuration = Path.home() / ".config" / "reclamos-vecinales" / "staging.json"
if configuration.stat().st_mode & 0o077:
    raise RuntimeError("El archivo de configuración requiere permisos 600.")
settings = json.loads(configuration.read_text(encoding="utf-8"))
stage_password = settings.pop("STAGING_PASSWORD")
if not isinstance(stage_password, str) or len(stage_password) < 24:
    raise RuntimeError("La clave de acceso a la prueba debe tener al menos 24 caracteres.")
for name in ("RV_ORIGIN", "RV_DATA", "RV_SECRET", "RV_ADMIN_PASSWORD"):
    os.environ[name] = settings[name]
os.environ.update(RV_DEMO="0", RV_STAGING="1", RV_CONTACT_ENABLED="0", RV_PRIVACY_TEXT="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import application as platform

expected = b"Basic " + base64.b64encode(("prueba:" + stage_password).encode())

def application(environ, start_response):
    if not hmac.compare_digest(environ.get("HTTP_AUTHORIZATION", "").encode(), expected):
        start_response("401 Unauthorized", [
            ("WWW-Authenticate", 'Basic realm="Prueba de Reclamos Vecinales"'),
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Cache-Control", "no-store"),
        ])
        return ["Acceso reservado a la prueba.".encode()]
    return platform(environ, start_response)
