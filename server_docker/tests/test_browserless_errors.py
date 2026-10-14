import unittest
from unittest.mock import patch

from server_docker import app as appmod
from server_docker.job_runner import is_retryable_error


class BrowserlessErrorTests(unittest.TestCase):
    def test_card_timeout_is_typed_retryable_and_does_not_leak_chat(self):
        class FakeResponse:
            status_code = 502
            text = "Error: YUANBAO_CARD_TIMEOUT:{\"chat\":\"PRIVATE_CHAT_CONTENT\"}"

        with patch.object(appmod.requests, "post", return_value=FakeResponse()):
            with self.assertRaises(appmod.AppError) as caught:
                appmod.browserless_function("function-code", {}, timeout=300)
        error = caught.exception
        self.assertEqual(error.code, "YUANBAO_CARD_TIMEOUT")
        self.assertEqual(error.status, 502)
        self.assertTrue(is_retryable_error(error))
        self.assertNotIn("PRIVATE_CHAT_CONTENT", error.message)
        self.assertIsNone(error.detail)

    def test_login_required_failure_does_not_retry(self):
        class FakeResponse:
            status_code = 502
            text = "Error: YUANBAO_LOGIN_REQUIRED: PRIVATE_SESSION_TEXT"

        with patch.object(appmod.requests, "post", return_value=FakeResponse()):
            with self.assertRaises(appmod.AppError) as caught:
                appmod.browserless_function("function-code", {}, timeout=300)
        self.assertEqual(caught.exception.code, "YUANBAO_LOGIN_REQUIRED")
        self.assertEqual(caught.exception.status, 401)
        self.assertFalse(is_retryable_error(caught.exception))
        self.assertIsNone(caught.exception.detail)

    def test_unknown_browserless_error_is_generic_and_safe(self):
        class FakeResponse:
            status_code = 502
            text = "PRIVATE_USER_CHAT_AND_COOKIES"

        with patch.object(appmod.requests, "post", return_value=FakeResponse()):
            with self.assertRaises(appmod.AppError) as caught:
                appmod.browserless_function("function-code", {}, timeout=300)
        self.assertEqual(caught.exception.code, "BROWSERLESS_ERROR")
        self.assertNotIn("PRIVATE_USER_CHAT_AND_COOKIES", caught.exception.message)
        self.assertIsNone(caught.exception.detail)

    def test_browserless_script_failure_is_safe_and_retryable(self):
        class FakeResponse:
            status_code = 502
            text = "Error: WECHAT_VIDEO_URL_MISSING: SESSION_DONT_COPY"

        with patch.object(appmod.requests, "post", return_value=FakeResponse()):
            with self.assertRaises(appmod.AppError) as caught:
                appmod.browserless_function("function-code", {}, timeout=300)
        self.assertEqual(caught.exception.code, "WECHAT_VIDEO_URL_MISSING")
        self.assertTrue(is_retryable_error(caught.exception))
        self.assertNotIn("SESSION_DONT_COPY", caught.exception.message)

    def test_transport_error_does_not_include_browserless_token(self):
        from requests.exceptions import ConnectionError
        with patch.object(appmod.requests, "post", side_effect=ConnectionError(
            "http://browserless:3000/function?token=PRIVATE_TOKEN_VALUE"
        )):
            with self.assertRaises(appmod.AppError) as caught:
                appmod.browserless_function("code", {}, timeout=300)
        self.assertEqual(caught.exception.code, "BROWSERLESS_UNREACHABLE")
        self.assertNotIn("PRIVATE_TOKEN_VALUE", caught.exception.message)

    def test_http_200_script_error_is_classified_without_payload(self):
        class FakeResponse:
            status_code = 200
            def json(self):
                return {"error": "YUANBAO_CARD_TIMEOUT: PRIVATE_CHAT_MESSAGE"}
        with patch.object(appmod.requests, "post", return_value=FakeResponse()):
            with self.assertRaises(appmod.AppError) as caught:
                appmod.browserless_function("code", {}, timeout=300)
        self.assertEqual(caught.exception.code, "YUANBAO_CARD_TIMEOUT")
        self.assertNotIn("PRIVATE_CHAT_MESSAGE", caught.exception.message)
        self.assertIsNone(caught.exception.detail)

    def test_card_budget_and_secret_log_suppression(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        script = (root / "browserless_function.js").read_text("utf-8")
        app_compose = (root / "docker-compose.yml").read_text("utf-8")
        browser_compose = (root / "docker-compose.browserless.yml").read_text("utf-8")
        self.assertIn('timeout: 110000', script)
        self.assertNotIn('body.slice(-1200)', script)
        self.assertIn('BROWSER_TIMEOUT: "${BROWSER_TIMEOUT:-300}"', app_compose)
        self.assertIn('CONNECTION_TIMEOUT: "${BROWSERLESS_CONNECTION_TIMEOUT:-360000}"', browser_compose)
        self.assertIn('DEBUG: "-*"', browser_compose)


if __name__ == "__main__":
    unittest.main()
