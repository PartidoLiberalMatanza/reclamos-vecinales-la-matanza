"""Crea una copia consistente de SQLite, incluidas las fotos."""
import argparse
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing

from database import DATA

def backup(destination):
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = DATA / "reclamos.sqlite3"
    if not source.is_file():
        raise SystemExit("No se encontró la base de datos de origen.")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = destination / f"reclamos-{timestamp}.sqlite3"
    descriptor, temporary = tempfile.mkstemp(dir=destination, suffix=".tmp")
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db:
            with closing(sqlite3.connect(temporary)) as copy:
                db.backup(copy)
                if copy.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise RuntimeError("La copia no pasó la comprobación de integridad.")
        Path(temporary).replace(output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return output

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(backup(args.destination.resolve()))
