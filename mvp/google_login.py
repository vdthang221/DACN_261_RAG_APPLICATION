import base64
import hashlib
import json
import os
import secrets
import hmac
from http.cookies import SimpleCookie
import time
import urllib.parse
import urllib.error
import urllib.request

try:
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
except ImportError:  # pragma: no cover
    id_token = None
    google_requests = None


AUTH_COOKIE = "google_login"
SESSION_COOKIE = "session"
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUER = "https://accounts.google.com"
STATE_TTL = 600
SESSION_TTL = 7 * 24 * 60 * 60


class LoginError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise LoginError("not_configured")
    return value


def _callback():
    value = _env("GOOGLE_REDIRECT_URI")
    try:
        parsed = urllib.parse.urlparse(value)
    except ValueError:
        raise LoginError("not_configured")
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise LoginError("not_configured")
    if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise LoginError("not_configured")
    if (parsed.query or parsed.fragment or parsed.username or parsed.password
            or parsed.path != "/auth/google/callback" or not parsed.hostname):
        raise LoginError("not_configured")
    return value


def configured():
    try:
        _env("GOOGLE_CLIENT_ID")
        _env("GOOGLE_CLIENT_SECRET")
        _callback()
        return id_token is not None and google_requests is not None
    except LoginError:
        return False


def initialize(db):
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS students (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS google_logins (
            state TEXT PRIMARY KEY,
            browser TEXT NOT NULL,
            nonce TEXT NOT NULL,
            verifier TEXT NOT NULL,
            expires REAL NOT NULL
        );
        DELETE FROM google_logins WHERE expires <= strftime('%s','now');
        DELETE FROM sessions
         WHERE user_id NOT IN (SELECT id FROM students);
        """
    )
    db.commit()


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cookies(header):
    try:
        parsed = SimpleCookie(header or "")
        return {key: value.value for key, value in parsed.items()}
    except Exception:
        return {}


def _secure():
    return os.getenv("GOOGLE_REDIRECT_URI", "").startswith("https://") or os.getenv("COOKIE_SECURE") == "1"


def _cookie(name, value, maxage, samesite):
    bits = [
        "%s=%s" % (name, value),
        "Path=/auth/google" if name == AUTH_COOKIE else "Path=/",
        "Max-Age=%d" % maxage,
        "HttpOnly",
        "SameSite=%s" % samesite,
    ]
    if _secure():
        bits.append("Secure")
    return "; ".join(bits)


def _clear_cookie(name, path="/"):
    bits = [
        "%s=" % name,
        "Path=%s" % path,
        "Max-Age=0",
        "HttpOnly",
        "SameSite=Lax",
    ]
    if _secure():
        bits.append("Secure")
    return "; ".join(bits)


def _pkce():
    verifier = _b64(secrets.token_bytes(32))
    challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def start(connect, cookie_header):
    if not configured():
        raise LoginError("not_configured")

    old = _cookies(cookie_header).get(AUTH_COOKIE)
    state = _b64(secrets.token_bytes(32))
    nonce = _b64(secrets.token_bytes(32))
    verifier, challenge = _pkce()
    browser = _b64(secrets.token_bytes(32))
    now = time.time()

    with connect() as db:
        db.execute(
            "DELETE FROM google_logins WHERE expires <= ?",
            (now,),
        )
        db.execute(
            """
            INSERT INTO google_logins(state,browser,nonce,verifier,expires)
            VALUES(?,?,?,?,?)
            """,
            (state, browser, nonce, verifier, now + STATE_TTL),
        )
        if old:
            db.execute("DELETE FROM google_logins WHERE browser = ?", (old,))

    params = {
        "client_id": _env("GOOGLE_CLIENT_ID"),
        "redirect_uri": _callback(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "hd": "hcmut.edu.vn",
    }
    params["prompt"] = "select_account"
    location = GOOGLE_AUTH + "?" + urllib.parse.urlencode(params)
    return location, _cookie(AUTH_COOKIE, browser, STATE_TTL, "Lax")


def _query_value(query, key):
    values = query.get(key, [])
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str) or len(values[0]) > 4096:
        raise LoginError("invalid_callback")
    return values[0]


def _post_form(url, values):
    body = urllib.parse.urlencode(values).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("oversized")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("invalid response")
            return result
    except urllib.error.HTTPError as exc:
        exc.close()
        raise LoginError("token_exchange_failed") from None
    except (OSError, ValueError, TypeError):
        raise LoginError("token_exchange_failed") from None


def _verified_claims(raw, nonce):
    try:
        request = google_requests.Request()
        def bounded_request(*args, **kwargs):
            kwargs["timeout"] = 10
            return request(*args, **kwargs)
        try:
            claims = id_token.verify_oauth2_token(
                raw, bounded_request, _env("GOOGLE_CLIENT_ID")
            )
        finally:
            request.session.close()
    except Exception:
        raise LoginError("invalid_identity")

    if not isinstance(claims, dict):
        raise LoginError("invalid_identity")
    if (type(claims.get("exp")) not in (int, float) or claims["exp"] <= time.time()
            or type(claims.get("iat")) not in (int, float) or claims["iat"] > time.time() + 30
            or not isinstance(claims.get("sub"), str) or not 1 <= len(claims["sub"]) <= 255
            or (claims.get("azp") is not None and claims["azp"] != _env("GOOGLE_CLIENT_ID"))):
        raise LoginError("invalid_identity")
    if claims.get("iss") not in (GOOGLE_ISSUER, "accounts.google.com"):
        raise LoginError("invalid_identity")
    if claims.get("aud") != _env("GOOGLE_CLIENT_ID"):
        raise LoginError("invalid_identity")
    if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(claims["nonce"].encode(), nonce.encode()):
        raise LoginError("invalid_identity")
    if claims.get("email_verified") is not True:
        raise LoginError("email_unverified")

    email = claims.get("email")
    hd = claims.get("hd")
    if (
        not isinstance(email, str)
        or not isinstance(hd, str)
        or hd != "hcmut.edu.vn"
        or len(email) > 254 or email != email.strip()
        or email.count("@") != 1 or not email.split("@")[0]
        or email.split("@")[1].lower() != "hcmut.edu.vn"
    ):
        raise LoginError("email_domain")
    return claims


def finish(connect, query, cookie_header):
    state = _query_value(query, "state")
    browser = _cookies(cookie_header).get(AUTH_COOKIE)
    if not configured():
        raise LoginError("not_configured")
    if not 20 <= len(state) <= 200 or not browser or len(browser) > 200:
        raise LoginError("invalid_callback")

    now = time.time()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """
            SELECT browser,nonce,verifier,expires
              FROM google_logins
             WHERE state = ?
            """,
            (state,),
        ).fetchone()
        if not row or not hmac.compare_digest(row["browser"].encode(), browser.encode()) or row["expires"] <= now:
            raise LoginError("invalid_state")
        db.execute("DELETE FROM google_logins WHERE state = ?", (state,))

    if "error" in query:
        raise LoginError("cancelled")
    code = _query_value(query, "code")
    if not code:
        raise LoginError("invalid_callback")

    token = _post_form(
        GOOGLE_TOKEN,
        {
            "code": code,
            "client_id": _env("GOOGLE_CLIENT_ID"),
            "client_secret": _env("GOOGLE_CLIENT_SECRET"),
            "redirect_uri": _callback(),
            "grant_type": "authorization_code",
            "code_verifier": row["verifier"],
        },
    )
    raw = token.get("id_token")
    if not isinstance(raw, str) or len(raw) > 16000:
        raise LoginError("invalid_identity")
    claims = _verified_claims(raw, row["nonce"])

    uid = "google:" + claims["sub"]
    email = claims["email"].lower()
    name = claims.get("name")
    name = name[:150] if isinstance(name, str) and name else email
    session = _b64(secrets.token_bytes(32))
    with connect() as db:
        db.execute(
            """
            INSERT INTO students(id,email,name) VALUES(?,?,?)
            ON CONFLICT(id) DO UPDATE SET email=excluded.email,name=excluded.name
            """,
            (uid, email, name),
        )
        old_session = _cookies(cookie_header).get(SESSION_COOKIE)
        if old_session:
            db.execute("DELETE FROM sessions WHERE token = ?", (_hash(old_session),))
        db.execute(
            "INSERT INTO sessions(token,user_id,expires) VALUES(?,?,?)",
            (_hash(session), uid, now + SESSION_TTL),
        )

    return _cookie(SESSION_COOKIE, session, SESSION_TTL, "Strict")
