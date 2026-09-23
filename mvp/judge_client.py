"""Railway-side HTTP client for the CodeLit GCP judge gateway."""

from dataclasses import dataclass
import json
import os
from urllib.parse import urlparse
import urllib.error
import urllib.request


MAX_RESPONSE_BYTES = 150_000


class JudgeClientError(RuntimeError):
    """Base error for judge configuration, transport, or response failures."""


class JudgeNotConfiguredError(JudgeClientError):
    pass


class JudgeAuthenticationError(JudgeClientError):
    pass


class JudgeUnavailableError(JudgeClientError):
    pass


class JudgeInvalidResponseError(JudgeClientError):
    pass


@dataclass(frozen=True)
class JudgeConfig:
    url: str
    token: str
    timeout: float = 65.0

    @classmethod
    def from_env(cls):
        url = os.getenv("GCP_JUDGE_URL", "").strip()
        token = os.getenv("GCP_JUDGE_TOKEN", "").strip()
        try:
            timeout = float(os.getenv("GCP_JUDGE_TIMEOUT", "65"))
        except ValueError as exc:
            raise JudgeNotConfiguredError("GCP_JUDGE_TIMEOUT must be numeric.") from exc
        if not url or len(token) < 32:
            raise JudgeNotConfiguredError(
                "Set GCP_JUDGE_URL and a GCP_JUDGE_TOKEN of at least 32 characters."
            )
        parsed = urlparse(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise JudgeNotConfiguredError("GCP_JUDGE_URL must be a plain HTTP(S) base URL.")
        if not 1 <= timeout <= 120:
            raise JudgeNotConfiguredError("GCP_JUDGE_TIMEOUT must be between 1 and 120 seconds.")
        return cls(url=url.rstrip("/"), token=token, timeout=timeout)


class JudgeClient:
    def __init__(self, config):
        self.config = config

    @classmethod
    def from_env(cls):
        return cls(JudgeConfig.from_env())

    @staticmethod
    def validate_result(payload, expected_test_count):
        if (
            not isinstance(payload, dict)
            or type(payload.get("passed")) is not bool
            or not isinstance(payload.get("tests"), list)
            or not isinstance(payload.get("compile_error", ""), str)
        ):
            raise JudgeInvalidResponseError("Judge gateway returned an invalid result schema.")
        if payload["passed"] and (
            len(payload["tests"]) != expected_test_count
            or not all(test.get("passed") is True for test in payload["tests"])
        ):
            raise JudgeInvalidResponseError(
                "Judge gateway did not prove that every testcase passed."
            )
        return payload

    def judge(self, code, tests):
        body = json.dumps({"code": code, "tests": tests}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.config.url + "/judge",
            data=body,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.config.token}",
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "CodeLit-Railway/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            try:
                exc.read(8_192)
                if exc.code == 401:
                    raise JudgeAuthenticationError(
                        "GCP judge rejected the configured token."
                    ) from exc
                raise JudgeUnavailableError(
                    f"GCP judge returned infrastructure HTTP {exc.code}."
                ) from exc
            finally:
                exc.close()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise JudgeUnavailableError(
                "GCP judge is unavailable or the request timed out."
            ) from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise JudgeInvalidResponseError("Judge gateway response is too large.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JudgeInvalidResponseError(
                "Judge gateway returned invalid JSON."
            ) from exc
        return self.validate_result(payload, len(tests))
