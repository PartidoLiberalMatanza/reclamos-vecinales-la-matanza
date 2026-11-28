"""Generate private settings without replacing an existing setup."""
import json
import os
import re
import secrets
import sys
from pathlib import Path

def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"https://[a-zA-Z0-9.-]+", sys.argv[1]):
        raise SystemExit("Indicá el origen HTTPS de la aplicación, sin barra final.")
    os.umask(0o077)
    config_dir = Path.home() / ".config" / "reclamos-vecinales"
    config_dir.mkdir(parents=True, exist_ok=True)
    destination = config_dir / "staging.json"
    settings = {
        "RV_ORIGIN": sys.argv[1],
        "RV_DATA": str(Path.home() / "reclamos-datos-prueba"),
        "RV_SECRET": secrets.token_urlsafe(48),
        "RV_ADMIN_PASSWORD": secrets.token_urlsafe(24),
        "STAGING_PASSWORD": secrets.token_urlsafe(24),
    }
    try:
        with destination.open("x", encoding="utf-8") as output:
            json.dump(settings, output, indent=2)
    except FileExistsError:
        raise SystemExit("La configuración ya existe. Se conservaron las claves anteriores.")
    print(f"Configuración privada creada en {destination}")
    print("Usuario del sitio de prueba: prueba")
    print("Clave de acceso:", settings["STAGING_PASSWORD"])
    print("Clave del panel de administración:", settings["RV_ADMIN_PASSWORD"])

if __name__ == "__main__":
    main()
