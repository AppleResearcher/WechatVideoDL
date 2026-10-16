"""Contract tests for the Apple-Design responsive UI; browser QA is separate."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AppleUIDesignTests(unittest.TestCase):
    def source(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_history_actions_have_exact_labels_order_and_original_links(self):
        js = self.source("static/app.js")
        segment = js.split(
            'const actions = document.createElement("div"); actions.className = "history-actions"'
        )[1].split('const detail = document.createElement("div")')[0]
        labels = ['"ALL"', '"AI解析"', '"旁白"', '"MP4"', '"详情"', '"删除"']
        offsets = [segment.index(label) for label in labels]
        self.assertEqual(offsets, sorted(offsets))
        expected_mapping = [
            'job.bundle?.download_path',
            'job.text?.download_path',
            'job.transcript?.download_path',
            'job.video?.download_path',
        ]
        self.assertEqual([segment.index(x) for x in expected_mapping],
                         sorted(segment.index(x) for x in expected_mapping))
        self.assertIn("actions.append(detailBtn, del)", segment)
        self.assertIn("detailBtn.setAttribute", js)
        self.assertIn('"aria-expanded", "false"', js)
        self.assertIn('"No VIDEO"', js)

    def test_workspace_uses_matching_download_semantics(self):
        js = self.source("static/app.js")
        segment = js.split('downloadLinks.replaceChildren();')[1].split('    }', 1)[0]
        labels = ['"ALL"', '"AI解析"', '"旁白"', '"MP4"']
        offsets = [segment.index(label) for label in labels]
        self.assertEqual(offsets, sorted(offsets))
        self.assertIn('data.transcript?.download_path', segment)

    def test_mobile_safe_area_controls_and_contrast(self):
        css = self.source("static/app.css")
        self.assertIn('@media (max-width:640px)', css)
        self.assertIn('grid-template-columns:repeat(3,minmax(0,1fr))', css)
        self.assertIn('min-height:44px', css)
        self.assertIn('safe-area-inset-bottom', css)
        self.assertIn('prefers-reduced-motion:reduce', css)
        self.assertIn('prefers-reduced-transparency:reduce', css)
        self.assertIn(':focus-visible', css)
        self.assertIn('var(--accent-ink)', css)
        self.assertIn('#235dbe', css)
        self.assertIn('#ad2839', css)

    def test_semantic_navigation_and_form_labels(self):
        base = self.source("templates/base.html")
        history = self.source("templates/history.html")
        login = self.source("templates/login.html")
        self.assertIn('aria-current="page"', base)
        self.assertIn('class="primary-nav"', base)
        self.assertIn('class="header-utilities"', base)
        self.assertIn('aria-label="外观主题"', base)
        self.assertIn('for="history-filter"', history)
        self.assertNotIn('autofocus', login)
        self.assertIn('autocomplete="current-password"', login)


if __name__ == "__main__":
    unittest.main()
