import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATA = Path(os.environ.get("RV_DATA", "./private-data")).resolve()
SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
 id TEXT PRIMARY KEY, created INTEGER NOT NULL, category TEXT NOT NULL,
 locality TEXT NOT NULL, place TEXT NOT NULL, description TEXT NOT NULL,
 latitude REAL NOT NULL, longitude REAL NOT NULL, name TEXT, email TEXT,
 tracking TEXT NOT NULL, visibility TEXT NOT NULL DEFAULT 'pending',
 status TEXT NOT NULL DEFAULT 'Registrado', official_ref TEXT NOT NULL DEFAULT '',
 official_agency TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS photos (
 id TEXT PRIMARY KEY, report TEXT NOT NULL REFERENCES reports(id), image BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS contacts (
 id TEXT PRIMARY KEY, created INTEGER NOT NULL, locality TEXT NOT NULL,
 email TEXT NOT NULL, handled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS codes (
 email TEXT PRIMARY KEY, digest TEXT NOT NULL, expires INTEGER NOT NULL,
 attempts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS supports (
 report TEXT NOT NULL REFERENCES reports(id), voter TEXT NOT NULL,
 PRIMARY KEY(report, voter)
);
CREATE TABLE IF NOT EXISTS admin_sessions (
 token TEXT PRIMARY KEY, expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS limits (
 bucket TEXT NOT NULL, period INTEGER NOT NULL, count INTEGER NOT NULL,
 PRIMARY KEY(bucket, period)
);
CREATE INDEX IF NOT EXISTS reports_public ON reports(visibility, created);
CREATE INDEX IF NOT EXISTS photos_report ON photos(report);
CREATE TABLE IF NOT EXISTS updates (
 id TEXT PRIMARY KEY, report TEXT NOT NULL REFERENCES reports(id),
 created INTEGER NOT NULL, status TEXT NOT NULL, agency TEXT NOT NULL, ref TEXT NOT NULL
);
"""

@contextmanager
def database():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(DATA / "reclamos.sqlite3", timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()

def initialize():
    with database() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
