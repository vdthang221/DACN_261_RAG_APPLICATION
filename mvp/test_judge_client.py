"""Tests for Railway's GCP judge client."""

import io
import json
import os
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from judge_client import (
    JudgeAuthenticationError,
    JudgeClient,
    JudgeConfig,
    JudgeInvalidResponseError,
    JudgeNotConfiguredError,
    JudgeUnavailableError,
)


class JudgeConfigTests(unittest.TestCase):
    def test_requires_url_and_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(JudgeNotConfiguredError):
                JudgeConfig.from_env()

    def test_reads_environment(self):
        with patch.dict(os.environ, {
            "GCP_JUDGE_URL": "http://judge.internal:8000/",
            "GCP_JUDGE_TOKEN": "token-0123456789-abcdefghijklmnop",
            "GCP_JUDGE_TIMEOUT": "70",
        }, clear=True):
            config = JudgeConfig.from_env()
        self.assertEqual(config.url, "http://judge.internal:8000")
        self.assertEqual(config.token, "token-0123456789-abcdefghijklmnop")
        self.assertEqual(config.timeout, 70)


class JudgeClientTests(unittest.TestCase):
    def setUp(self):
        self.client = JudgeClient(JudgeConfig(
            "http://judge:8000", "secret-0123456789-abcdefghijklmnop", 65
        ))
        self.tests = [{"input": "", "expected": "ok"}]

    @patch("urllib.request.urlopen")
    def test_success_and_bearer_header(self, urlopen):
        result = {
            "passed": True,
            "compile_error": "",
            "tests": [{"passed": True}],
        }
        response = MagicMock()
        response.read.return_value = json.dumps(result).encode()
        response.__enter__.return_value = response
        urlopen.return_value = response
        self.assertEqual(self.client.judge("code", self.tests), result)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://judge:8000/judge")
        self.assertEqual(
            request.headers["Authorization"],
            "Bearer secret-0123456789-abcdefghijklmnop",
        )

    @patch("urllib.request.urlopen")
    def test_gateway_unavailable(self, urlopen):
        urlopen.side_effect = urllib.error.URLError("offline")
        with self.assertRaises(JudgeUnavailableError):
            self.client.judge("code", self.tests)

    @patch("urllib.request.urlopen")
    def test_authentication_failure(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "http://judge:8000/judge", 401, "Unauthorized", {}, io.BytesIO(b"{}")
        )
        with self.assertRaises(JudgeAuthenticationError):
            self.client.judge("code", self.tests)

    @patch("urllib.request.urlopen")
    def test_invalid_json_response(self, urlopen):
        response = MagicMock()
        response.read.return_value = b"not-json"
        response.__enter__.return_value = response
        urlopen.return_value = response
        with self.assertRaises(JudgeInvalidResponseError):
            self.client.judge("code", self.tests)

    @patch("urllib.request.urlopen")
    def test_invalid_passed_response(self, urlopen):
        response = MagicMock()
        response.read.return_value = json.dumps({
            "passed": True,
            "compile_error": "",
            "tests": [],
        }).encode()
        response.__enter__.return_value = response
        urlopen.return_value = response
        with self.assertRaises(JudgeInvalidResponseError):
            self.client.judge("code", self.tests)


if __name__ == "__main__":
    unittest.main()
