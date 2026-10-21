"""GT Custom Edition shared label: public identity without local secrets."""
import unittest
from unittest.mock import patch
from pathlib import Path

from server_docker import app as application

ROOT = Path(__file__).resolve().parents[1]


class CustomEditionBrandingTests(unittest.TestCase):
    def test_login_uses_shared_footer(self):
        with patch.object(application, "current_user", return_value=None), application.app.test_client() as client:
            response = client.get("/login")
            self.assertEqual(response.status_code, 200)
            body = response.get_data(as_text=True)
            self.assertEqual(body.count("GT Custom Edition"), 1)
            self.assertIn('class="login-panel-footer"', body)
            self.assertIn('aria-label="版本信息"', body)
            self.assertIn("topgptus/WechatVideoDL", body)

    def test_all_authenticated_views_share_base_footer(self):
        base = (ROOT / "templates/base.html").read_text("utf-8")
        partial = '_gt_custom_edition_footer.html'
        self.assertEqual(base.count('include "' + partial + '"'), 1)
        for name in ("index", "history", "batches", "settings"):
            view = (ROOT / f"templates/{name}.html").read_text("utf-8")
            self.assertIn('extends "base.html"', view, name)
            self.assertNotIn('block shell', view, name)
        login = (ROOT / "templates/login.html").read_text("utf-8")
        self.assertEqual(login.count('include "' + partial + '"'), 1)

    def test_identity_and_upstream_are_semantically_distinct(self):
        fragment = (ROOT / "templates/_gt_custom_edition_footer.html").read_text("utf-8")
        self.assertIn("<strong>GT Custom Edition</strong>", fragment)
        self.assertIn('rel="noopener noreferrer"', fragment)
        self.assertIn("基于 ", fragment)
        css = (ROOT / "static/app.css").read_text("utf-8")
        for token in ("--surface-2", "--border", "--text", "--muted", "--accent-ink"):
            self.assertIn(token, css)
        self.assertIn("prefers-reduced-motion:reduce", css)


if __name__ == "__main__":
    unittest.main()
