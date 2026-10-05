import tempfile
import unittest
from pathlib import Path

from server_docker.job_files import safe_owned_path, write_analysis_file


class JobFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.download_dir = Path(self.tmp.name)
        self.job = {
            "id": "wxv_000012",
            "input_url": "https://weixin.qq.com/sph/demo",
            "prompt": "总结重点",
            "preset_name": "结构化知识笔记",
            "yuanbao_content": "第一点\n第二点",
            "created_at": "2026-10-03T12:00:00+00:00",
            "video_title": "拿破仑密信",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_txt(self):
        path = write_analysis_file(self.download_dir, self.job, "txt")
        self.assertEqual(path.name, "拿破仑密信__000012.txt")
        text = path.read_text("utf-8")
        self.assertIn("ID: wxv_000012", text)
        self.assertIn("INPUT_URL: https://weixin.qq.com/sph/demo", text)
        self.assertIn("PROMPT:\n总结重点", text)
        self.assertIn("YUANBAO_CONTENT:\n第一点\n第二点", text)

    def test_write_markdown(self):
        path = write_analysis_file(self.download_dir, self.job, "md")
        self.assertEqual(path.name, "拿破仑密信__000012.md")
        text = path.read_text("utf-8")
        self.assertTrue(text.startswith("# 拿破仑密信\n"))
        self.assertIn("- Task ID: `wxv_000012`", text)
        self.assertIn("- Source: https://weixin.qq.com/sph/demo", text)
        self.assertIn("- Preset: 结构化知识笔记", text)
        self.assertIn("## Prompt\n\n总结重点", text)
        self.assertIn("## Yuanbao Response\n\n第一点\n第二点", text)

    def test_invalid_format_rejected(self):
        with self.assertRaises(ValueError):
            write_analysis_file(self.download_dir, self.job, "html")

    def test_legacy_job_without_title_uses_fallback_filename(self):
        legacy = dict(self.job)
        legacy.pop("video_title", None)
        path = write_analysis_file(self.download_dir, legacy, "md")
        self.assertEqual(path.name, "微信视频号__000012.md")

    def test_safe_owned_path_accepts_owned_artifacts_only(self):
        unicode_name = "拿破仑密信__000012.mp4"
        self.assertEqual(
            safe_owned_path(self.download_dir, unicode_name),
            self.download_dir / unicode_name,
        )
        self.assertEqual(
            safe_owned_path(self.download_dir, "wxv_000012.md"),
            self.download_dir / "wxv_000012.md",
        )
        self.assertIsNone(safe_owned_path(self.download_dir, "../wxv_000012.mp4"))
        self.assertIsNone(safe_owned_path(self.download_dir, "folder/file.mp4"))
        self.assertIsNone(safe_owned_path(self.download_dir, "/etc/passwd"))
        self.assertIsNone(safe_owned_path(self.download_dir, "anything.exe"))
        self.assertIsNone(safe_owned_path(self.download_dir, "title__000012.mp4", {"md"}))



if __name__ == "__main__":
    unittest.main()
