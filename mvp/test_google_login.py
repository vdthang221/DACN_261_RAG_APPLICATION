import base64
import hashlib
import json
import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import google_login
import server


class TestGoogleLogin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.tmp.close()
        self.env = patch.dict(os.environ, {
            "DATABASE_PATH": self.tmp.name,
            "GOOGLE_CLIENT_ID": "test-client",
            "GOOGLE_CLIENT_SECRET": "test-secret",
            "GOOGLE_REDIRECT_URI":
                "http://127.0.0.1:8000/auth/google/callback",
            "COOKIE_SECURE": "0",
        }, clear=False)
        self.env.start()
        server.init_db()
        self.db = sqlite3.connect(self.tmp.name)
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.db.close()
        self.env.stop()
        os.unlink(self.tmp.name)

    def connect(self):
        return server.connect()

    def start(self, cookie=""):
        location, browser = google_login.start(self.connect, cookie)
        return parse_qs(urlparse(location).query), browser

    def claims(self, expected_nonce, **overrides):
        value = {
            "iss": "https://accounts.google.com",
            "aud": "test-client",
            "azp": "test-client",
            "exp": time.time() + 600,
            "iat": time.time(),
            "nonce": expected_nonce,
            "sub": "subject-1",
            "email": "student@hcmut.edu.vn",
            "email_verified": True,
            "hd": "hcmut.edu.vn",
            "name": "Student",
        }
        value.update(overrides)
        return value

    def finish(self, query, cookie, claims=None, token_error=None):
        if claims is None:
            claims = self.claims(query["nonce"][0])
        with patch.object(google_login, "_post_form") as post, \
             patch.object(google_login.id_token, "verify_oauth2_token",
                          return_value=claims):
            if token_error:
                post.side_effect = token_error
            else:
                post.return_value = {"id_token": "raw-token"}
            return google_login.finish(
                self.connect,
                {"state": query["state"], "code": ["code"]},
                cookie,
            )

    def test_start_finish_and_pkce(self):
        query, browser = self.start()
        self.assertEqual(query["client_id"], ["test-client"])
        self.assertEqual(query["redirect_uri"],
                         ["http://127.0.0.1:8000/auth/google/callback"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["scope"], ["openid email profile"])
        session_cookie = self.finish(query, browser)
        self.assertIn("session=", session_cookie)
        row = self.db.execute("SELECT * FROM students").fetchone()
        self.assertEqual(row["id"], "google:subject-1")
        stored = self.db.execute("SELECT * FROM sessions").fetchone()
        self.assertEqual(stored["token"], hashlib.sha256(
            session_cookie.split("=", 1)[1].split(";", 1)[0].encode()
        ).hexdigest())

    def test_identity_is_stable_and_session_rotates(self):
        q, browser = self.start()
        first = self.finish(q, browser)
        old = first.split(";", 1)[0]
        q, browser = self.start()
        second = self.finish(q, browser + "; " + old, self.claims(q["nonce"][0], name="Changed"))
        self.assertNotEqual(first, second)
        self.assertEqual(self.db.execute("SELECT count(*) FROM students").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM sessions").fetchone()[0], 1)
        old_hash = hashlib.sha256(old.split("=", 1)[1].encode()).hexdigest()
        self.assertIsNone(self.db.execute("SELECT * FROM sessions WHERE token=?", (old_hash,)).fetchone())

    def test_old_browser_state_is_removed_on_new_start(self):
        q1, c1 = self.start()
        self.start(c1)
        with self.assertRaisesRegex(google_login.LoginError, "invalid_state"):
            self.finish(q1, c1)

    def test_state_replay_wrong_browser_expiry_and_cancel(self):
        q, c = self.start()
        self.finish(q, c)
        with self.assertRaisesRegex(google_login.LoginError, "invalid_state"):
            self.finish(q, c)

        q, c = self.start()
        with self.assertRaisesRegex(google_login.LoginError, "invalid_state"):
            self.finish(q, c.replace("google_login=", "google_login=wrong"))

        # Incorrect browser must not burn the legitimate login.
        self.finish(q, c)
        q, c = self.start()
        self.db.execute("UPDATE google_logins SET expires = 0")
        self.db.commit()
        with self.assertRaisesRegex(google_login.LoginError, "invalid_state"):
            self.finish(q, c)

        q, c = self.start()
        with self.assertRaisesRegex(google_login.LoginError, "cancelled"):
            google_login.finish(self.connect, {
                "state": q["state"], "error": ["access_denied"]
            }, c)
        with self.assertRaisesRegex(google_login.LoginError, "invalid_state"):
            self.finish(q, c)

    def test_claim_validation(self):
        fields = [
            ("iss", "bad"), ("aud", "bad"), ("azp", "bad"),
            ("exp", time.time() - 1), ("iat", time.time() + 31),
            ("sub", ""), ("sub", 123), ("nonce", "bad"),
        ]
        for field, value in fields:
            q, c = self.start()
            with self.assertRaisesRegex(google_login.LoginError, "invalid_identity"):
                self.finish(q, c, self.claims(q["nonce"][0], **{field: value}))

    def test_email_domain_validation(self):
        cases = [
            {"email": "hcmut.edu.vn"},
            {"email": "@hcmut.edu.vn"},
            {"email": "x@y@hcmut.edu.vn"},
            {"email": "student@gmail.com"},
            {"email": "x@hcmut.edu.vn.evil", "hd": "hcmut.edu.vn"},
            {"email": "x@sub.hcmut.edu.vn", "hd": "sub.hcmut.edu.vn"},
            {"email": "x@hcmut.edu.vn", "hd": None},
            {"email": "x@hcmut.edu.vn", "email_verified": False},
            {"email": "x@hcmut.edu.vn ", "hd": "hcmut.edu.vn"},
        ]
        for change in cases:
            q, c = self.start()
            code = "email_unverified" if change.get("email_verified") is False else "email_domain"
            with self.assertRaisesRegex(google_login.LoginError, code):
                self.finish(q, c, self.claims(q["nonce"][0], **change))

    def test_token_exchange_network_error(self):
        q, c = self.start()
        with patch("google_login.urllib.request.urlopen", side_effect=OSError("offline")):
            with self.assertRaisesRegex(google_login.LoginError, "token_exchange_failed"):
                google_login.finish(self.connect, {"state": q["state"], "code": ["code"]}, c)

    def test_missing_config_has_no_bypass(self):
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": ""}):
            self.assertFalse(google_login.configured())
            with self.assertRaisesRegex(google_login.LoginError, "not_configured"):
                google_login.start(self.connect, "")

    def test_callback_settings(self):
        for value in (
            "http://external.example/auth/google/callback",
            "http://127.0.0.1/auth/google/wrong",
            "http://127.0.0.1/auth/google/callback?x=1",
        ):
            with patch.dict(os.environ, {"GOOGLE_REDIRECT_URI": value}):
                self.assertFalse(google_login.configured())

    def test_old_demo_sessions_are_removed_but_attempts_remain(self):
        self.db.execute("INSERT INTO sessions VALUES ('old','SV01',?)", (time.time() + 1000,))
        self.db.execute("""INSERT INTO attempts(id,user_id,state,stage,body,created)
            VALUES('historic','SV01','failed_tests','generate','{}',?)""", (time.time(),))
        self.db.commit()
        google_login.initialize(self.db)
        self.assertEqual(self.db.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM attempts WHERE id='historic'").fetchone()[0], 1)



class TestRealSignature(unittest.TestCase):
    def test_corrupted_signature_rejected_with_mocked_cert_transport(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        from google.auth import crypt, jwt

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        signer = crypt.RSASigner.from_string(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()), key_id="k")
        public_pem = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        claims = {"iss": "https://accounts.google.com", "aud": "test-client",
                  "sub": "signed-student", "iat": int(time.time()), "exp": int(time.time()) + 600,
                  "nonce": "nonce", "email": "student@hcmut.edu.vn",
                  "email_verified": True, "hd": "hcmut.edu.vn"}
        token = jwt.encode(signer, claims)
        response = Mock(status=200, data=json.dumps({"k": public_pem}).encode())
        request = Mock(return_value=response)
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "test-client"}), \
             patch.object(google_login.google_requests, "Request", return_value=request):
            self.assertEqual(google_login._verified_claims(token, "nonce")["sub"], "signed-student")
            self.assertEqual(request.call_args.kwargs["timeout"], 10)
            parts = token.split(b".")
            raw = base64.urlsafe_b64decode(parts[2] + b"=" * (-len(parts[2]) % 4))
            parts[2] = base64.urlsafe_b64encode(bytes([raw[0] ^ 1]) + raw[1:]).rstrip(b"=")
            with self.assertRaisesRegex(google_login.LoginError, "invalid_identity"):
                google_login._verified_claims(b".".join(parts), "nonce")


if __name__ == "__main__":
    unittest.main()
