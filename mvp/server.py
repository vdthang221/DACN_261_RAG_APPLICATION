"""CodeLit Sprint 2. Railway API with remote GCP Docker judging."""
import concurrent.futures
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time as datetime_time, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import threading
import time
import uuid
from zoneinfo import ZoneInfo
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from bank import parse_xml, problem_xml, moodle_xml, validate_problem
from judge_client import JudgeClient
from llm import ProviderError, ProviderResponse, build_request, call_gemini, demo_result, encode_payload, validate_result
import google_login

ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()
STOP = threading.Event()
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=1)
ACTIVE = {"judging", "generate_pending", "generating", "feedback_pending", "feedback_running"}
PACIFIC = ZoneInfo("America/Los_Angeles")


@dataclass(frozen=True)
class QuotaDecision:
    granted: bool
    call_id: str
    wait_until: float = 0
    reason: str = ""
    reset_at: float = 0


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


def env_int(name, default, minimum=1, maximum=1_000_000):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}.")
    return value


def quota_bucket():
    bucket = os.getenv("LLM_QUOTA_BUCKET", "codelit-google-project").strip()
    if not re.fullmatch(r"[a-zA-Z0-9._:/-]{1,128}", bucket):
        raise RuntimeError("LLM_QUOTA_BUCKET is invalid.")
    return bucket


def quota_limits():
    return {
        "rpm": env_int("LLM_RPM", 5, maximum=1000),
        "rpd": env_int("LLM_RPD", 20, maximum=1_000_000),
        "tpm": env_int("LLM_INPUT_TPM", 250000, maximum=100_000_000),
        "queue_timeout": env_int("LLM_QUEUE_TIMEOUT_SECONDS", 120, maximum=3600),
        "retry_limit": env_int("LLM_RETRY_LIMIT", 3, maximum=10),
        "queue_max": env_int("LLM_QUEUE_MAX", 20, maximum=10000),
    }


def quota_day_window(now):
    local = datetime.fromtimestamp(now, PACIFIC)
    tomorrow = local.date() + timedelta(days=1)
    reset = datetime.combine(tomorrow, datetime_time.min, tzinfo=PACIFIC)
    return local.date().isoformat(), reset.timestamp()


def attempt_from_row(row):
    return {**json.loads(row["body"]), **{k: row[k] for k in
        ["id", "user_id", "state", "stage", "created", "next_run", "tries"]}}


def attempt_fields(a):
    return {k: v for k, v in a.items()
            if k not in {"id", "user_id", "state", "stage", "created", "next_run", "tries"}}


def save_attempt_db(db, a):
    db.execute("UPDATE attempts SET state=?,stage=?,body=?,next_run=?,tries=? WHERE id=?",
               (a["state"], a["stage"], json.dumps(attempt_fields(a), ensure_ascii=False),
                a.get("next_run", 0), a.get("tries", 0), a["id"]))


def log_llm(event, **fields):
    safe = {"event": event, "component": "gemini", "at": round(time.time(), 3)}
    safe.update({key: value for key, value in fields.items() if value is not None})
    print(json.dumps(safe, ensure_ascii=False, separators=(",", ":")), flush=True)


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
        -- Legacy table kept for one-time migration from deployments before the
        -- shared atomic limiter.
        CREATE TABLE IF NOT EXISTS llm_usage(at REAL NOT NULL, tokens INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS llm_calls(
          call_id TEXT PRIMARY KEY,
          bucket TEXT NOT NULL,
          job_id TEXT NOT NULL,
          stage TEXT NOT NULL,
          attempt_no INTEGER NOT NULL,
          reserved_at REAL NOT NULL,
          quota_day TEXT NOT NULL,
          input_tokens_est INTEGER NOT NULL,
          input_tokens_actual INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          total_tokens INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL,
          error_code TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS llm_calls_minute ON llm_calls(bucket,reserved_at);
        CREATE INDEX IF NOT EXISTS llm_calls_day ON llm_calls(bucket,quota_day);
        CREATE INDEX IF NOT EXISTS llm_calls_job ON llm_calls(job_id,stage,attempt_no);
        CREATE TABLE IF NOT EXISTS llm_cooldowns(
          bucket TEXT PRIMARY KEY,
          until_at REAL NOT NULL,
          reason TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        google_login.initialize(db)
        for p in json.loads((ROOT / "seed.json").read_text(encoding="utf-8")):
            validate_problem(p)
            db.execute("INSERT OR IGNORE INTO problems VALUES (?,?)", (p["id"], json.dumps(p, ensure_ascii=False)))
        bucket = quota_bucket()
        migrated = db.execute("SELECT 1 FROM settings WHERE key='llm_quota_v2_migrated'").fetchone()
        if not migrated:
            for row in db.execute("SELECT rowid,at,tokens FROM llm_usage ORDER BY at"):
                day, _ = quota_day_window(row["at"])
                db.execute("""INSERT OR IGNORE INTO llm_calls
                    (call_id,bucket,job_id,stage,attempt_no,reserved_at,quota_day,input_tokens_est,status,error_code)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (f"legacy:{row['rowid']}:{row['at']}", bucket, "legacy", "legacy", row["rowid"],
                     row["at"], day, row["tokens"], "legacy", "legacy_migration"))
            old_cooldown = db.execute("SELECT value FROM settings WHERE key='cooldown'").fetchone()
            if old_cooldown:
                db.execute("INSERT OR REPLACE INTO llm_cooldowns VALUES (?,?,?)",
                           (bucket, float(old_cooldown[0]), "legacy"))
            db.execute("INSERT INTO settings VALUES ('llm_quota_v2_migrated','1')")
        # A restart cannot fabricate a pass, lose answers, or blindly duplicate
        # a provider request whose outcome is unknown.
        db.execute("UPDATE attempts SET state='judge_error' WHERE state='judging'")
        for row in db.execute("SELECT * FROM attempts WHERE state IN ('generating','feedback_running')").fetchall():
            a = attempt_from_row(row)
            last = db.execute("""SELECT * FROM llm_calls WHERE job_id=? AND stage=?
                ORDER BY attempt_no DESC LIMIT 1""", (a["id"], a["stage"])).fetchone()
            if not last or last["status"] in {"sent", "ambiguous"}:
                if last and last["status"] == "sent":
                    db.execute("UPDATE llm_calls SET status='ambiguous',error_code='restart_after_send' WHERE call_id=?",
                               (last["call_id"],))
                a.update(state="llm_error", error_code="provider_outcome_unknown", retry_at=0,
                         error="Server khởi động lại khi request Gemini đang chạy; không tự gọi lại để tránh sinh trùng.")
            elif last["status"] == "reserved":
                db.execute("UPDATE llm_calls SET status='abandoned',error_code='restart_before_send' WHERE call_id=?",
                           (last["call_id"],))
                a["tries"] = max(a["tries"], last["attempt_no"])
                a["state"] = a["stage"] + "_pending"
            else:
                a.update(state="llm_error", error_code="provider_outcome_unknown", retry_at=0,
                         error="Trạng thái Gemini không nhất quán sau restart; chưa phát hành kết quả.")
            save_attempt_db(db, a)
        db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))


def all_problems():
    with connect() as db:
        return {row["id"]: json.loads(row["body"]) for row in db.execute("SELECT * FROM problems ORDER BY rowid")}


def get_attempt(aid):
    with connect() as db:
        row = db.execute("SELECT * FROM attempts WHERE id=?", (aid,)).fetchone()
    if row is None:
        raise ValueError("Không tìm thấy lần nộp.")
    return attempt_from_row(row)


def save_attempt(a):
    with connect() as db:
        save_attempt_db(db, a)


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


def reserve_budget(tokens, job_id=None, stage="generate", attempt_no=1, call_id=None, now=None):
    """Atomically reserve one real provider call in the shared SQLite bucket."""
    now = time.time() if now is None else float(now)
    limits = quota_limits()
    bucket = quota_bucket()
    day, reset_at = quota_day_window(now)
    job_id = job_id or "test-job"
    call_id = call_id or f"test:{uuid.uuid4().hex}"
    if tokens > limits["tpm"]:
        raise ProviderError("Nội dung vượt giới hạn input TPM cấu hình.", code="local_input_tpm")
    with connect() as db:
        # This is the cross-thread/process correctness boundary. SQLite obtains
        # the writer lock before any counter is read.
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM llm_calls WHERE call_id=?", (call_id,)).fetchone():
            raise ProviderError("Lượt gọi này đã được cấp quota; không gọi trùng.", code="duplicate_provider_call")
        daily_count = db.execute("SELECT count(*) FROM llm_calls WHERE bucket=? AND quota_day=?",
                                 (bucket, day)).fetchone()[0]
        if daily_count >= limits["rpd"]:
            raise ProviderError("Đã hết quota Gemini trong ngày theo giờ Pacific.", code="local_daily_quota",
                                retry_at=reset_at)
        minute = list(db.execute("""SELECT reserved_at,
            max(input_tokens_est,input_tokens_actual) AS input_tokens
            FROM llm_calls WHERE bucket=? AND reserved_at>? ORDER BY reserved_at""",
            (bucket, now - 60)))
        wait_until = now
        reasons = []
        cooldown = db.execute("SELECT until_at,reason FROM llm_cooldowns WHERE bucket=?", (bucket,)).fetchone()
        if cooldown and cooldown["until_at"] > now:
            if cooldown["reason"] == "provider_daily_quota":
                raise ProviderError("Google báo quota ngày chưa được reset.", code="provider_daily_quota",
                                    retry_at=max(reset_at, cooldown["until_at"]))
            wait_until = max(wait_until, cooldown["until_at"])
            reasons.append(cooldown["reason"])
        # Conservative pacing avoids a burst of five simultaneous requests.
        if minute:
            wait_until = max(wait_until, minute[-1]["reserved_at"] + 60 / limits["rpm"])
            reasons.append("rpm_spacing")
        if len(minute) >= limits["rpm"]:
            wait_until = max(wait_until, minute[len(minute) - limits["rpm"]]["reserved_at"] + 60.001)
            reasons.append("rolling_rpm")
        used = sum(row["input_tokens"] for row in minute)
        remaining = used
        if used + tokens > limits["tpm"]:
            for row in minute:
                remaining -= row["input_tokens"]
                if remaining + tokens <= limits["tpm"]:
                    wait_until = max(wait_until, row["reserved_at"] + 60.001)
                    reasons.append("input_tpm")
                    break
        if wait_until > now:
            return QuotaDecision(False, call_id, wait_until, "+".join(dict.fromkeys(reasons)), reset_at)
        db.execute("""INSERT INTO llm_calls
            (call_id,bucket,job_id,stage,attempt_no,reserved_at,quota_day,input_tokens_est,status)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (call_id, bucket, job_id, stage, attempt_no, now, day, tokens, "reserved"))
        # Keep enough history for debugging around a day boundary without
        # allowing this table to grow forever.
        db.execute("DELETE FROM llm_calls WHERE reserved_at<?", (now - 8 * 86400,))
    return QuotaDecision(True, call_id, reset_at=reset_at)


def set_cooldown(until_at, reason):
    if until_at <= 0:
        return
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT until_at FROM llm_cooldowns WHERE bucket=?", (quota_bucket(),)).fetchone()
        if not current or current["until_at"] < until_at:
            db.execute("INSERT OR REPLACE INTO llm_cooldowns VALUES (?,?,?)",
                       (quota_bucket(), until_at, reason))


def gemini_calls_for_job(job_id):
    with connect() as db:
        return db.execute("SELECT count(*) FROM llm_calls WHERE job_id=? AND status!='legacy'", (job_id,)).fetchone()[0]


def save_attempt_and_call(a, call_id, status, error_code="", usage=None):
    usage = usage or {}
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute("""UPDATE llm_calls SET status=?,error_code=?,input_tokens_actual=?,output_tokens=?,total_tokens=?
            WHERE call_id=?""", (status, error_code, usage.get("prompt_tokens", 0),
            usage.get("output_tokens", 0), usage.get("total_tokens", 0), call_id)).rowcount
        if changed != 1:
            raise RuntimeError("Reserved Gemini quota row is missing.")
        save_attempt_db(db, a)


def mark_call_sent(a, call_id):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute("UPDATE llm_calls SET status='sent' WHERE call_id=? AND status='reserved'",
                             (call_id,)).rowcount
        if changed != 1:
            raise ProviderError("Không thể đánh dấu lượt gọi duy nhất; đã chặn request trùng.",
                                code="duplicate_provider_call")
        save_attempt_db(db, a)


def apply_llm_result(a, result, call_id=None, usage=None):
    a.update(error="", error_code="", retry_at=0, quota_reset_at=0, next_run=0)
    if a["stage"] == "generate":
        a.update(questions=result, state="mcq_ready")
    else:
        a.update(feedback=result, state="completed")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if a["stage"] == "generate":
            for q in result:
                encoded = json.dumps({**q, "problem_id": a["problem"]["id"]}, ensure_ascii=False, sort_keys=True)
                db.execute("INSERT OR IGNORE INTO mcq_bank VALUES (?,?)",
                           (hashlib.sha256(encoded.encode()).hexdigest(), encoded))
        if call_id:
            usage = usage or {}
            changed = db.execute("""UPDATE llm_calls SET status='success',error_code='',input_tokens_actual=?,
                output_tokens=?,total_tokens=? WHERE call_id=?""", (usage.get("prompt_tokens", 0),
                usage.get("output_tokens", 0), usage.get("total_tokens", 0), call_id)).rowcount
            if changed != 1:
                raise RuntimeError("Reserved Gemini quota row is missing.")
        save_attempt_db(db, a)


def process_llm(a, now=None):
    now = time.time() if now is None else float(now)
    call_id = None
    call_reserved = False
    try:
        payload = build_request(a)
        if a["mode"] == "demo":
            result = validate_result(demo_result(a), a)
            apply_llm_result(a, result)
            return
        if not os.getenv("GEMINI_API_KEY"):
            raise ProviderError("Chưa cấu hình GEMINI_API_KEY trên server. Cấu hình rồi bấm Thử lại.",
                                code="provider_not_configured")
        limits = quota_limits()
        if a["tries"] >= limits["retry_limit"]:
            raise ProviderError(f"Đã hết {limits['retry_limit']} lượt gọi Gemini cho giai đoạn này.",
                                code="retry_exhausted")
        call_no = a["tries"] + 1
        call_id = f"{a['id']}:{a['stage']}:{call_no}"
        # UTF-8 JSON bytes are a deliberately conservative local estimate and
        # avoid spending another API call merely to count tokens.
        estimated_tokens = len(encode_payload(payload))
        decision = reserve_budget(estimated_tokens, a["id"], a["stage"], call_no, call_id, now)
        if not decision.granted:
            wait = decision.wait_until - now
            queue_started_at = a.get("queue_started_at") or now
            queue_deadline = queue_started_at + limits["queue_timeout"]
            a["queue_started_at"] = queue_started_at
            if decision.wait_until > queue_deadline:
                a.update(state="llm_error", error_code="quota_wait_too_long", retry_at=decision.wait_until,
                         quota_reset_at=decision.reset_at,
                         error="Hàng đợi quota vượt thời gian chờ cho phép; hãy thử lại sau.")
                log_llm("rejected", job_id=a["id"], stage=a["stage"], reason=decision.reason,
                        wait_seconds=round(now - queue_started_at, 3),
                        retry_at=round(decision.wait_until, 3), input_tokens_est=estimated_tokens)
            else:
                a.update(state=a["stage"] + "_pending", next_run=decision.wait_until,
                         error_code="quota_wait", retry_at=decision.wait_until,
                         quota_reset_at=decision.reset_at,
                         error="Đang chờ lượt gọi Gemini trong hàng đợi quota.")
                log_llm("queued", job_id=a["id"], stage=a["stage"], reason=decision.reason,
                        wait_seconds=round(wait, 3), input_tokens_est=estimated_tokens)
            save_attempt(a)
            return
        call_reserved = True
        a.pop("queue_started_at", None)
        a["tries"] = call_no
        a.update(error="", error_code="", retry_at=0, quota_reset_at=decision.reset_at)
        mark_call_sent(a, call_id)
        log_llm("call_started", job_id=a["id"], stage=a["stage"], call_no=call_no,
                calls_for_job=gemini_calls_for_job(a["id"]), input_tokens_est=estimated_tokens)
        response = call_gemini(payload)
        if isinstance(response, ProviderResponse):
            result = response.result
            usage = {"prompt_tokens": response.prompt_tokens, "output_tokens": response.output_tokens,
                     "total_tokens": response.total_tokens}
        else:  # Test doubles may return the validated provider JSON directly.
            result, usage = response, {}
        result = validate_result(result, a)
        apply_llm_result(a, result, call_id, usage)
        log_llm("call_succeeded", job_id=a["id"], stage=a["stage"], call_no=call_no,
                calls_for_job=gemini_calls_for_job(a["id"]), **usage)
    except ProviderError as exc:
        retry_limit = quota_limits()["retry_limit"]
        a.update(error=str(exc), error_code=exc.code, retry_at=exc.retry_at or 0)
        if exc.code in {"local_daily_quota", "provider_daily_quota"}:
            _, reset_at = quota_day_window(now)
            a["quota_reset_at"] = max(exc.retry_at, reset_at)
            a["retry_at"] = a["quota_reset_at"]
            a["state"] = "llm_error"
            if exc.code == "provider_daily_quota":
                set_cooldown(a["quota_reset_at"], "provider_daily_quota")
        elif exc.retryable and a["tries"] < retry_limit:
            delay = max(exc.retry_after, 15 * (2 ** max(0, a["tries"] - 1))) + random.uniform(0, 3)
            retry_at = now + delay
            a["retry_at"] = retry_at
            if delay <= quota_limits()["queue_timeout"]:
                a.update(state=a["stage"] + "_pending", next_run=retry_at)
                if exc.code in {"provider_minute_quota", "provider_rate_limit_unknown"}:
                    set_cooldown(retry_at, exc.code)
            else:
                a["state"] = "llm_error"
        else:
            a["state"] = "llm_error"
        if call_reserved and exc.code != "duplicate_provider_call":
            status = "ambiguous" if exc.code == "provider_outcome_unknown" else "failed"
            save_attempt_and_call(a, call_id, status, exc.code)
        else:
            save_attempt(a)
        log_llm("call_failed", job_id=a["id"], stage=a["stage"], call_no=a.get("tries", 0),
                calls_for_job=gemini_calls_for_job(a["id"]), reason=exc.code,
                retry_at=round(a.get("retry_at", 0), 3) or None)
    except Exception:
        a.update(state="llm_error", error_code="invalid_result", retry_at=0,
                 error="LLM trả cấu trúc không hợp lệ. Kết quả chưa hoàn chỉnh không được phát hành.")
        if call_reserved:
            save_attempt_and_call(a, call_id, "failed", "invalid_result")
        else:
            save_attempt(a)
        log_llm("call_failed", job_id=a["id"], stage=a["stage"], call_no=a.get("tries", 0),
                calls_for_job=gemini_calls_for_job(a["id"]), reason="invalid_result")


def claim_llm_job(now=None):
    now = time.time() if now is None else now
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""SELECT * FROM attempts
            WHERE state IN ('generate_pending','feedback_pending') AND next_run<=?
            ORDER BY created LIMIT 1""", (now,)).fetchone()
        if not row:
            return None
        pending = row["state"]
        running = "generating" if row["stage"] == "generate" else "feedback_running"
        if db.execute("UPDATE attempts SET state=? WHERE id=? AND state=?", (running, row["id"], pending)).rowcount != 1:
            return None
        updated = db.execute("SELECT * FROM attempts WHERE id=?", (row["id"],)).fetchone()
        return attempt_from_row(updated)


def llm_worker():
    while not STOP.wait(0.5):
        try:
            a = claim_llm_job()
            if a:
                process_llm(a)
        except Exception:
            # Keep worker alive. No source, prompts, credentials, or student data in logs.
            log_llm("worker_error", reason="transient_internal_error")


class APIError(Exception):
    def __init__(self, status, message, code="request_error", **details):
        self.status, self.message, self.code, self.details = status, message, code, details

    def payload(self):
        return {"error": self.message, "code": self.code, **self.details}


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
            self.reply(exc.payload(), exc.status)
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
            return self.reply({"mode": os.getenv("LLM_MODE", "gemini"), "model": os.getenv("GEMINI_MODEL", "gemini-3.8-flash"), "llm_configured": bool(os.getenv("GEMINI_API_KEY")), "language": "C++17", "google_configured": google_login.configured()})
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
            self.reply(exc.payload(), exc.status)
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
            problems = all_problems()
            if not isinstance(pid, str) or pid not in problems:
                raise ValueError("Bài toán không tồn tại.")
            if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9-]{8,80}", key):
                raise ValueError("Request ID không hợp lệ.")
            aid = hashlib.sha256((uid + key).encode()).hexdigest()[:32]
            with connect() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute("SELECT * FROM attempts WHERE id=?", (aid,)).fetchone()
                if existing:
                    old = attempt_from_row(existing)
                    if old["code"] != code or old["problem"]["id"] != pid:
                        raise APIError(409, "Request ID đã được dùng cho nội dung khác.", "idempotency_conflict")
                    return self.reply(public_attempt(old))
                rows = list(db.execute("SELECT state,created FROM attempts WHERE user_id=?", (uid,)))
                if any(row["state"] in ACTIVE for row in rows):
                    raise APIError(409, "Bạn đang có một bài đang xử lý. Chờ hoàn tất trước khi nộp tiếp.",
                                   "user_job_active")
                if sum(row["created"] > time.time() - 60 for row in rows) >= 5:
                    raise APIError(429, "Tối đa 5 lần nộp/phút. Vui lòng đợi một chút.",
                                   "submission_rate_limit", retry_at=time.time() + 60)
                queued = db.execute("SELECT count(*) FROM attempts WHERE state IN (?,?,?,?,?)",
                    tuple(ACTIVE)).fetchone()[0]
                if queued >= quota_limits()["queue_max"]:
                    raise APIError(429, "Hàng đợi xử lý đang đầy; chưa tạo thêm job Gemini.", "llm_queue_full",
                                   retry_at=time.time() + 15)
                body = {"problem": problems[pid], "code": code, "mode": os.getenv("LLM_MODE", "gemini"),
                        "error": "", "error_code": "", "retry_at": 0, "quota_reset_at": 0}
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
                if not judge and a["tries"] >= quota_limits()["retry_limit"]:
                    raise APIError(409, "Đã hết giới hạn gọi Gemini cho giai đoạn này.", "retry_exhausted")
                a.update(state="judging" if judge else a["stage"] + "_pending",
                         tries=0 if judge else a["tries"], next_run=0, error="", error_code="", retry_at=0)
                a.pop("queue_started_at", None)
                save_attempt(a)
                if judge:
                    POOL.submit(judge_attempt, a["id"])
                return self.reply(public_attempt(a), 202)
        raise APIError(404, "Không tìm thấy thao tác.")


def validate_runtime_config():
    if os.getenv("LLM_MODE", "gemini") not in {"gemini", "demo"}:
        raise RuntimeError("LLM_MODE must be gemini or demo.")
    quota_limits()
    quota_bucket()
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    if not re.fullmatch(r"[a-zA-Z0-9.-]+", model):
        raise RuntimeError("GEMINI_MODEL is invalid.")
    try:
        timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    except ValueError as exc:
        raise RuntimeError("LLM_TIMEOUT_SECONDS must be numeric.") from exc
    if not 1 <= timeout <= 300:
        raise RuntimeError("LLM_TIMEOUT_SECONDS must be between 1 and 300.")
    env_int("LLM_MAX_OUTPUT_TOKENS", 4096, minimum=1, maximum=65536)


def main():
    load_env()
    try:
        validate_runtime_config()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
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
