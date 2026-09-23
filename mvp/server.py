"""CodeLit Sprint 2. Railway API with remote GCP Docker judging."""
import concurrent.futures
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import random
import sqlite3
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from bank import parse_xml, problem_xml, moodle_xml, validate_problem
from judge_client import JudgeClient
from llm import ProviderError, build_request, call_gemini, demo_result, validate_result
import google_login

ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()
STOP = threading.Event()
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=1)
ACTIVE = {"judging", "generate_pending", "generating", "feedback_pending", "feedback_running"}


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@contextmanager
def connect():
    db = sqlite3.connect(os.getenv("DATABASE_PATH", str(ROOT / "data" / "codelit.db")), timeout=10)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def init_db():
    path = Path(os.getenv("DATABASE_PATH", str(ROOT / "data" / "codelit.db")))
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS problems(id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, user_id TEXT NOT NULL, state TEXT NOT NULL,
          stage TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL, next_run REAL NOT NULL DEFAULT 0, tries INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS attempt_user ON attempts(user_id, created);
        CREATE TABLE IF NOT EXISTS mcq_bank(hash TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS llm_usage(at REAL NOT NULL, tokens INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        google_login.initialize(db)
        for p in json.loads((ROOT / "seed.json").read_text(encoding="utf-8")):
            validate_problem(p)
            db.execute("INSERT OR IGNORE INTO problems VALUES (?,?)", (p["id"], json.dumps(p, ensure_ascii=False)))
        # A restart cannot fabricate a pass or lose already submitted answers.
        db.execute("UPDATE attempts SET state='judge_error' WHERE state='judging'")
        db.execute("UPDATE attempts SET state='generate_pending' WHERE state='generating'")
        db.execute("UPDATE attempts SET state='feedback_pending' WHERE state='feedback_running'")
        db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))


def all_problems():
    with connect() as db:
        return {row["id"]: json.loads(row["body"]) for row in db.execute("SELECT * FROM problems ORDER BY rowid")}


def get_attempt(aid):
    with connect() as db:
        row = db.execute("SELECT * FROM attempts WHERE id=?", (aid,)).fetchone()
    if row is None:
        raise ValueError("Không tìm thấy lần nộp.")
    return {**json.loads(row["body"]), **{k: row[k] for k in ["id", "user_id", "state", "stage", "created", "next_run", "tries"]}}


def save_attempt(a):
    fields = {k: v for k, v in a.items() if k not in {"id", "user_id", "state", "stage", "created", "next_run", "tries"}}
    with connect() as db:
        db.execute("UPDATE attempts SET state=?,stage=?,body=?,next_run=?,tries=? WHERE id=?",
                   (a["state"], a["stage"], json.dumps(fields, ensure_ascii=False), a.get("next_run", 0), a.get("tries", 0), a["id"]))


def public_attempt(a):
    copy = json.loads(json.dumps(a))
    copy["problem"].pop("solution", None)
    if "answers" not in copy:
        copy["questions"] = [{k: q[k] for k in ["question", "options", "skill", "bloom"]} for q in copy.get("questions", [])]
    return copy


def run_judge(code, tests):
    return JudgeClient.from_env().judge(code, tests)


def judge_attempt(aid):
    try:
        a = get_attempt(aid)
        result = run_judge(a["code"], a["problem"]["tests"])
        with LOCK:
            a = get_attempt(aid)
            a.update(judge=result, state="generate_pending" if result["passed"] else "failed_tests", stage="generate", error="", next_run=0)
            save_attempt(a)
    except Exception as exc:
        with LOCK:
            a = get_attempt(aid)
            a.update(state="judge_error", error=str(exc) if isinstance(exc, RuntimeError) else "Lỗi hạ tầng judge; chưa chấm đạt.")
            save_attempt(a)


def reserve_budget(tokens, now=None):
    """One app instance; durable conservative rolling windows, including failed calls."""
    now = time.time() if now is None else now
    rpm, tpm, rpd = (max(1, int(os.getenv(k, default))) for k, default in [("LLM_RPM", "4"), ("LLM_INPUT_TPM", "20000"), ("LLM_RPD", "100")])
    if tokens > tpm:
        raise ProviderError("Nội dung vượt ngân sách input TPM cấu hình. Rút ngắn code hoặc nhờ giảng viên điều chỉnh quota.")
    with LOCK, connect() as db:
        usage = list(db.execute("SELECT at,tokens FROM llm_usage WHERE at>? ORDER BY at", (now - 86400,)))
        minute = [row for row in usage if row["at"] > now - 60]
        wait_until = now
        cooldown = db.execute("SELECT value FROM settings WHERE key='cooldown'").fetchone()
        if cooldown:
            wait_until = max(wait_until, float(cooldown[0]))
        if len(usage) >= rpd:
            wait_until = max(wait_until, usage[len(usage) - rpd]["at"] + 86401)
        if minute:
            wait_until = max(wait_until, minute[-1]["at"] + 60 / rpm)
        if len(minute) >= rpm:
            wait_until = max(wait_until, minute[len(minute) - rpm]["at"] + 61)
        total = sum(row["tokens"] for row in minute)
        for row in minute:
            if total + tokens <= tpm:
                break
            wait_until = max(wait_until, row["at"] + 61)
            total -= row["tokens"]
        if wait_until > now:
            return wait_until
        db.execute("INSERT INTO llm_usage VALUES (?,?)", (now, tokens))
        db.execute("DELETE FROM llm_usage WHERE at<?", (now - 86400,))
    return 0


def process_llm(a):
    try:
        if a["tries"] >= 3:
            raise ProviderError("Đã hết 3 lượt gọi tự động. Bấm Thử lại để bắt đầu một lượt mới.")
        payload = build_request(a)
        demo = a["mode"] == "demo"
        if not demo:
            if not os.getenv("GEMINI_API_KEY"):
                raise ProviderError("Chưa cấu hình GEMINI_API_KEY trên server. Cấu hình rồi bấm Thử lại.")
            # UTF-8 byte count is a deliberately conservative text-token estimate.
            delayed = reserve_budget(len(json.dumps(payload, ensure_ascii=False).encode()))
            if delayed:
                a.update(state=a["stage"] + "_pending", next_run=delayed, error="Đang chờ ngân sách API; hệ thống sẽ tự tiếp tục.")
                save_attempt(a)
                return
        a["tries"] += 1
        save_attempt(a)
        result = demo_result(a) if demo else call_gemini(payload)
        result = validate_result(result, a)
        a.update(error="", next_run=0)
        if a["stage"] == "generate":
            a.update(questions=result, state="mcq_ready")
            with connect() as db:
                for q in result:
                    encoded = json.dumps({**q, "problem_id": a["problem"]["id"]}, ensure_ascii=False, sort_keys=True)
                    db.execute("INSERT OR IGNORE INTO mcq_bank VALUES (?,?)", (hashlib.sha256(encoded.encode()).hexdigest(), encoded))
        else:
            a.update(feedback=result, state="completed")
        with LOCK:
            save_attempt(a)
    except ProviderError as exc:
        a["error"] = str(exc)
        if exc.retryable and a["tries"] < 3:
            delay = max(exc.retry_after, 15 * (2 ** max(0, a["tries"] - 1))) + random.uniform(0, 3)
            a.update(state=a["stage"] + "_pending", next_run=time.time() + delay)
            with connect() as db:
                db.execute("INSERT OR REPLACE INTO settings VALUES ('cooldown',?)", (str(a["next_run"]),))
        else:
            a["state"] = "llm_error"
        save_attempt(a)
    except Exception:
        a.update(state="llm_error", error="LLM trả cấu trúc không hợp lệ hoặc xử lý gặp lỗi. Chưa phát hành kết quả; có thể thử lại.")
        save_attempt(a)


def llm_worker():
    while not STOP.wait(0.5):
        try:
            with LOCK:
                with connect() as db:
                    row = db.execute("SELECT id FROM attempts WHERE state IN ('generate_pending','feedback_pending') AND next_run<=? ORDER BY created LIMIT 1", (time.time(),)).fetchone()
                if not row:
                    continue
                a = get_attempt(row["id"])
                a["state"] = "generating" if a["stage"] == "generate" else "feedback_running"
                save_attempt(a)
            process_llm(a)
        except Exception:
            # Keep worker alive. No source, prompts, credentials, or student data in logs.
            print("LLM worker: transient internal error", flush=True)


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def reply(self, data, status=200, headers=None, content_type="application/json; charset=utf-8"):
        body = json.dumps(data, ensure_ascii=False).encode() if content_type.startswith("application/json") else (data.encode() if isinstance(data, str) else data)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (headers.items() if isinstance(headers, dict) else headers or []):
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def identity(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie["session"].value
        except Exception:
            raise APIError(401, "Vui lòng đăng nhập bằng Google với email @hcmut.edu.vn.")
        with connect() as db:
            row = db.execute("""SELECT p.id,p.email,p.name FROM sessions s
                JOIN students p ON p.id=s.user_id WHERE s.token=? AND s.expires>?""",
                (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        if not row:
            raise APIError(401, "Phiên đăng nhập hết hạn.")
        return dict(row)

    def user(self):
        return self.identity()["id"]

    def admin(self):
        expected = os.getenv("ADMIN_TOKEN", "")
        supplied = self.headers.get("X-Admin-Token", "")
        if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
            raise APIError(403, "Cần mã quản trị hợp lệ (ADMIN_TOKEN) để quản lý ngân hàng.")

    def owned(self, aid):
        a = get_attempt(aid)
        if a["user_id"] != self.user():
            raise APIError(404, "Không tìm thấy lần nộp.")
        return a

    def do_GET(self):
        try:
            self.get()
        except APIError as exc:
            self.reply({"error": exc.message}, exc.status)
        except ValueError as exc:
            self.reply({"error": str(exc)}, 400)
        except Exception:
            self.reply({"error": "Server gặp lỗi; vui lòng thử lại."}, 500)

    def get(self):
        url = urlparse(self.path)
        path = url.path
        if path in {"/auth/google/start", "/auth/google/callback"}:
            headers = []
            try:
                if path == "/auth/google/start":
                    location, cookie = google_login.start(connect, self.headers.get("Cookie", ""))
                else:
                    if len(url.query) > 8192:
                        raise google_login.LoginError("invalid_callback")
                    try:
                        query = parse_qs(url.query, keep_blank_values=True, max_num_fields=10)
                    except ValueError:
                        raise google_login.LoginError("invalid_callback") from None
                    cookie = google_login.finish(connect, query, self.headers.get("Cookie", ""))
                    location = "/#problems"
                headers.append(("Set-Cookie", cookie))
            except google_login.LoginError as exc:
                allowed = {"not_configured", "invalid_callback", "invalid_state", "cancelled",
                           "token_exchange_failed", "invalid_identity", "email_unverified", "email_domain"}
                error = exc.code if exc.code in allowed else "login_failed"
                location = "/?login_error=" + error
            if path == "/auth/google/callback":
                headers.append(("Set-Cookie", google_login._clear_cookie("google_login", "/auth/google")))
            headers.append(("Location", location))
            return self.reply("", 302, headers=headers, content_type="text/plain; charset=utf-8")
        if path in {"/", "/app.js", "/style.css", "/favicon.svg"}:
            name = "index.html" if path == "/" else path[1:]
            mime = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8", "favicon.svg": "image/svg+xml"}[name]
            return self.reply((ROOT / "static" / name).read_bytes(), content_type=mime)
        if path == "/api/config":
            return self.reply({"mode": os.getenv("LLM_MODE", "gemini"), "model": os.getenv("GEMINI_MODEL", "gemini-3.6-flash"), "llm_configured": bool(os.getenv("GEMINI_API_KEY")), "language": "C++17", "google_configured": google_login.configured()})
        if path == "/api/me":
            return self.reply(self.identity())
        if path == "/api/problems":
            self.user()
            return self.reply([{k: v for k, v in p.items() if k != "solution"} for p in all_problems().values()])
        if path == "/api/attempts":
            uid = self.user()
            with connect() as db:
                rows = list(db.execute("SELECT id FROM attempts WHERE user_id=? ORDER BY created DESC LIMIT 100", (uid,)))
            attempts = [get_attempt(row[0]) for row in rows]
            return self.reply([{k: a.get(k) for k in ["id", "state", "created", "score", "mode"]} | {"title": a["problem"]["title"], "problem_id": a["problem"]["id"]} for a in attempts])
        if path.startswith("/api/attempts/"):
            return self.reply(public_attempt(self.owned(path.split("/")[-1])))
        if path == "/api/admin/export":
            self.admin()
            kind = parse_qs(url.query).get("kind", ["problems"])[0]
            if kind == "problems":
                xml = problem_xml(all_problems().values())
            elif kind == "mcqs":
                with connect() as db:
                    questions = [json.loads(row[0]) for row in db.execute("SELECT body FROM mcq_bank")]
                xml = moodle_xml(questions)
            else:
                raise ValueError("Loại export không hợp lệ.")
            return self.reply(xml, content_type="application/xml; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{kind}.xml"'})
        if path == "/api/admin/bank":
            self.admin()
            with connect() as db:
                count = db.execute("SELECT count(*) FROM mcq_bank").fetchone()[0]
            return self.reply({"problems": len(all_problems()), "mcqs": count})
        raise APIError(404, "Không tìm thấy trang.")

    def do_POST(self):
        try:
            if self.headers.get("X-Requested-With") != "CodeLit" or not self.headers.get("Content-Type", "").startswith("application/json"):
                raise APIError(403, "Yêu cầu phải đến từ ứng dụng CodeLit.")
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host"):
                raise APIError(403, "Origin không hợp lệ.")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 650000:
                raise APIError(413, "Dữ liệu quá lớn hoặc trống.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Cần JSON object.")
            with LOCK:
                self.post(urlparse(self.path).path, data)
        except APIError as exc:
            self.reply({"error": exc.message}, exc.status)
        except (ValueError, TypeError, KeyError) as exc:
            self.reply({"error": str(exc) if isinstance(exc, ValueError) else "Dữ liệu yêu cầu không hợp lệ."}, 400)
        except Exception:
            self.reply({"error": "Server gặp lỗi; dữ liệu đã lưu vẫn được giữ."}, 500)

    def post(self, path, data):
        if path == "/api/logout":
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            if "session" in cookie:
                with connect() as db:
                    db.execute("DELETE FROM sessions WHERE token=?", (hashlib.sha256(cookie["session"].value.encode()).hexdigest(),))
            return self.reply({"ok": True}, headers={"Set-Cookie": google_login._clear_cookie("session")})
        if path == "/api/admin/import":
            self.admin()
            kind, records = parse_xml(data.get("xml"), all_problems())
            added = 0
            with connect() as db:
                if kind == "problems":
                    # Atomic upsert. Existing attempts retain their own problem snapshot.
                    for p in records:
                        db.execute("INSERT OR REPLACE INTO problems VALUES (?,?)", (p["id"], json.dumps(p, ensure_ascii=False)))
                        added += 1
                else:
                    for q in records:
                        encoded = json.dumps(q, ensure_ascii=False, sort_keys=True)
                        cursor = db.execute("INSERT OR IGNORE INTO mcq_bank VALUES (?,?)", (hashlib.sha256(encoded.encode()).hexdigest(), encoded))
                        added += cursor.rowcount
            return self.reply({"kind": kind, "count": added, "received": len(records)})
        if path == "/api/submissions":
            uid = self.user()
            code, pid, key = data.get("code"), data.get("problem_id"), data.get("request_id")
            if not isinstance(code, str) or not code.strip() or len(code.encode()) > 12000:
                raise ValueError("Code cần 1–12000 byte.")
            if not isinstance(pid, str) or pid not in all_problems():
                raise ValueError("Bài toán không tồn tại.")
            if not isinstance(key, str) or not __import__('re').fullmatch(r"[a-zA-Z0-9-]{8,80}", key):
                raise ValueError("Request ID không hợp lệ.")
            aid = hashlib.sha256((uid + key).encode()).hexdigest()[:32]
            with connect() as db:
                if db.execute("SELECT 1 FROM attempts WHERE id=?", (aid,)).fetchone():
                    old = get_attempt(aid)
                    if old["code"] != code or old["problem"]["id"] != pid:
                        raise APIError(409, "Request ID đã được dùng cho nội dung khác.")
                    return self.reply(public_attempt(old))
                rows = list(db.execute("SELECT state,created FROM attempts WHERE user_id=?", (uid,)))
                if any(row["state"] in ACTIVE for row in rows):
                    raise APIError(409, "Bạn đang có một bài đang xử lý. Chờ hoàn tất trước khi nộp tiếp.")
                if sum(row["created"] > time.time() - 60 for row in rows) >= 5:
                    raise APIError(429, "Tối đa 5 lần nộp/phút. Vui lòng đợi một chút.")
                body = {"problem": all_problems()[pid], "code": code, "mode": os.getenv("LLM_MODE", "gemini"), "error": ""}
                db.execute("INSERT INTO attempts(id,user_id,state,stage,body,created) VALUES (?,?,'judging','generate',?,?)", (aid, uid, json.dumps(body, ensure_ascii=False), time.time()))
            POOL.submit(judge_attempt, aid)
            return self.reply(public_attempt(get_attempt(aid)), 202)
        if path.startswith("/api/attempts/"):
            parts = path.split("/")
            if len(parts) != 5:
                raise APIError(404, "Không tìm thấy thao tác.")
            a = self.owned(parts[3])
            if parts[4] == "answers":
                answers = data.get("answers")
                if not isinstance(answers, list) or len(answers) != 3 or any(type(n) is not int or not 0 <= n < 4 for n in answers):
                    raise ValueError("Trả lời đủ 3 câu, mỗi câu chọn 1 phương án.")
                if "answers" in a:
                    if answers != a["answers"]:
                        raise APIError(409, "Đã nộp câu trả lời; không thể thay đổi.")
                    return self.reply(public_attempt(a))
                if a["state"] != "mcq_ready":
                    raise APIError(409, "MCQ chưa sẵn sàng.")
                a.update(answers=answers, score=sum(value == q["answer"] for value, q in zip(answers, a["questions"])),
                         stage="feedback", state="feedback_pending", tries=0, next_run=0, error="")
                save_attempt(a)
                return self.reply(public_attempt(a), 202)
            if parts[4] == "retry":
                if a["state"] not in {"judge_error", "llm_error"}:
                    raise APIError(409, "Lần nộp này không cần retry.")
                with connect() as db:
                    rows = db.execute("SELECT id,state FROM attempts WHERE user_id=?", (a["user_id"],)).fetchall()
                if any(row["id"] != a["id"] and row["state"] in ACTIVE for row in rows):
                    raise APIError(409, "Bạn đang có một lần nộp khác đang xử lý.")
                judge = a["state"] == "judge_error"
                a.update(state="judging" if judge else a["stage"] + "_pending", tries=0, next_run=0, error="")
                save_attempt(a)
                if judge:
                    POOL.submit(judge_attempt, a["id"])
                return self.reply(public_attempt(a), 202)
        raise APIError(404, "Không tìm thấy thao tác.")


def main():
    load_env()
    if os.getenv("LLM_MODE", "gemini") not in {"gemini", "demo"}:
        raise SystemExit("LLM_MODE must be gemini or demo")
    init_db()
    threading.Thread(target=llm_worker, daemon=True).start()
    server = ThreadingHTTPServer((os.getenv("HOST", "127.0.0.1"), int(os.getenv("PORT", "8000"))), Handler)
    print(f"CodeLit: http://{server.server_address[0]}:{server.server_address[1]} | C++17 | LLM: {os.getenv('LLM_MODE', 'gemini')}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STOP.set()
        server.server_close()
        POOL.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
