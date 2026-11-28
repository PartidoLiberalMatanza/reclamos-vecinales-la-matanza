import base64
import io
import json
import os
import sqlite3
import tempfile
import unittest

from PIL import Image


class PlatformTest(unittest.TestCase):
    def test_registration_moderation_and_privacy(self):
        from app import DATA, ORIGIN, application, digest, initialize
        from backup import backup

        initialize()
        cookie = ""

        def call(path, payload=None, expected=200, session=False, origin=ORIGIN):
            path, _, query = path.partition("?")
            data = json.dumps(payload).encode()
            environment = {
                "PATH_INFO": "/api/" + path,
                "QUERY_STRING": query,
                "REQUEST_METHOD": "GET" if payload is None else "POST",
                "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": str(len(data)),
                "HTTP_ORIGIN": origin,
                "REMOTE_ADDR": "192.0.2.1",
                "HTTP_COOKIE": cookie if session else "",
                "wsgi.input": io.BytesIO(data),
            }
            metadata = []
            response = b"".join(application(environment, lambda status, headers: metadata.extend(
                (status, dict(headers)))))
            self.assertEqual(int(metadata[0].split()[0]), expected, (path, response[:300]))
            result = json.loads(response) if metadata[1]["Content-Type"].startswith("application/json") else response
            return result, metadata[1]

        buffer = io.BytesIO()
        image = Image.new("RGB", (20, 20))
        metadata = image.getexif()
        metadata[270] = "Metadato privado"
        image.save(buffer, "JPEG", exif=metadata)
        photo = base64.b64encode(buffer.getvalue()).decode()
        sample = {
            "category": "Alumbrado público", "locality": "Gregorio de Laferrere",
            "place": "Esquina de prueba", "description": "Una luminaria de prueba necesita mantenimiento.",
            "latitude": -34.75412, "longitude": -58.58998,
            "consent": True, "photos": [photo], "mode": "identified",
            "name": "Persona Ficticia", "email": "registrante@example.com",
        }
        call("reports", sample, expected=403, origin="https://example.com")
        call("reports", {**sample, "photos": ["aW52w6FsaWRv"]}, expected=400)
        report, _ = call("reports", sample)
        anonymous, _ = call("reports", {**sample, "mode": "anonymous", "photos": []})
        self.assertEqual(call("reports")[0], [])
        call("reports/" + report["id"], expected=404)
        call("admin", expected=401)
        _, headers = call("admin/login", {"password": os.environ["RV_ADMIN_PASSWORD"]})
        cookie = headers["Set-Cookie"].split(";")[0]
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        private, _ = call("admin", session=True)
        records = {row["id"]: row for row in private["reports"]}
        self.assertIsNone(records[anonymous["id"]]["email"])
        self.assertEqual(records[report["id"]]["email"], sample["email"])
        photo_id = records[report["id"]]["photos"][0]
        call("photos/" + photo_id, expected=404)
        review = {"id": report["id"], "visibility": "published", "status": "En trámite",
                  "agency": "Organismo de prueba", "ref": "EXP-PRUEBA-1", "place": sample["place"],
                  "description": sample["description"]}
        call("admin/moderate", review, expected=400, session=True)
        call("admin/moderate", {**review, "reviewed": True}, session=True)
        public, _ = call("reports/" + report["id"])
        self.assertEqual(public["latitude"], -34.754)
        self.assertFalse({"name", "email", "official_ref", "tracking"} & public.keys())
        image_bytes, _ = call("photos/" + photo_id)
        with Image.open(io.BytesIO(image_bytes)) as sanitized:
            self.assertFalse(sanitized.getexif())
        call("track", {"id": report["id"], "key": "incorrecta-123456789"}, expected=404)
        track, _ = call("track", report)
        self.assertEqual(track["history"][0]["ref"], review["ref"])

        management = {**report, "email": "gestion@example.com", "consent": True}
        call("management", {**management, "key": "incorrecta-123456789"}, expected=404)
        call("management", {**management, "consent": False}, expected=400)
        self.assertTrue(call("management", management)[0]["saved"])
        self.assertFalse(call("management", management)[0]["saved"])
        self.assertNotIn("gestion@example.com", json.dumps(call("reports")[0]))
        call("admin/management", {"id": report["id"]}, expected=401)
        call("admin/management", {"id": report["id"]}, session=True)
        self.assertEqual(call("admin", session=True)[0]["management"][0]["handled"], 1)
        call("admin/management", {"id": report["id"], "delete": True}, session=True)
        self.assertEqual(call("admin", session=True)[0]["management"], [])

        voter = "vecino@example.com"
        def code():
            call("code", {"email": voter})
            return (DATA / "demo-mail" / digest("mail:" + voter)).read_text()

        verification = code()
        attempt = {"id": report["id"], "email": voter}
        incorrect = "000000" if verification != "000000" else "111111"
        call("support", {**attempt, "code": incorrect}, expected=400)
        self.assertTrue(call("support", {**attempt, "code": verification})[0]["added"])
        call("support", {**attempt, "code": verification}, expected=400)
        self.assertFalse(call("support", {**attempt, "code": code()})[0]["added"])
        self.assertEqual(call("reports/" + report["id"])[0]["supports"], 1)
        call("code", {"email": voter})
        call("code", {"email": voter}, expected=429)
        contact = {"locality": "San Justo", "email": "consulta@example.com", "consent": False}
        call("contact", contact, expected=400)
        call("contact", {**contact, "consent": True})
        private, _ = call("admin", session=True)
        contact_id = private["contacts"][0]["id"]
        call("admin/contact", {"id": contact_id}, session=True)
        self.assertEqual(call("admin", session=True)[0]["contacts"][0]["handled"], 1)
        call("admin/contact", {"id": contact_id, "delete": True}, session=True)
        call("admin/redact", {"id": report["id"]}, session=True)
        private, _ = call("admin", session=True)
        self.assertEqual(private["contacts"], [])
        self.assertTrue(all(row["email"] is None for row in private["reports"]))

        copied = backup(DATA / "copies")
        with sqlite3.connect(copied) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("SELECT image FROM photos").fetchone()[0], image_bytes)
        self.assertEqual(copied.stat().st_mode & 0o077, 0)
        call("admin/moderate", {**review, "visibility": "hidden"}, session=True)
        call("photos/" + photo_id, expected=404)
        call("admin/moderate", {**review, "id": anonymous["id"], "reviewed": True}, session=True)
        self.assertEqual(len(call("reports?category=Alumbrado+p%C3%BAblico&locality=Gregorio+de+Laferrere")[0]), 1)
        self.assertEqual(call("reports?category=Maltrato+y+protecci%C3%B3n+animal")[0], [])
        self.assertEqual(call("reports?locality=San+Justo")[0], [])
        call("reports?category=invalida", expected=400)
        call("admin/logout", {}, session=True)
        call("admin", expected=401, session=True)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="rv-test-") as data:
        os.environ.update(RV_DATA=data, RV_DEMO="1", RV_ORIGIN="http://127.0.0.1:8000",
                          RV_SECRET="test-secret-not-used-in-production-123456",
                          RV_ADMIN_PASSWORD="test-password-not-used-in-production")
        unittest.main()
