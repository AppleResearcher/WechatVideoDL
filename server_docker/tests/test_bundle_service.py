import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from server_docker.bundle_service import ensure_bundle


class BundleServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job = {
            "id": "wxv_000012",
            "video_title": "拿破仑密信",
            "text_filename": "拿破仑密信__000012.md",
            "video_filename": "拿破仑密信__000012.mp4",
            "thumbnail_filename": "拿破仑密信__000012.jpg",
        }
        (self.root / self.job["text_filename"]).write_text("md", "utf-8")
        (self.root / self.job["video_filename"]).write_bytes(b"mp4")
        (self.root / self.job["thumbnail_filename"]).write_bytes(b"jpg")

    def tearDown(self):
        self.tmp.cleanup()

    def test_bundle_name_and_members_use_shared_title_stem(self):
        path = ensure_bundle(self.root, self.job)
        self.assertEqual(path.name, "拿破仑密信__000012.zip")
        with zipfile.ZipFile(path) as zf:
            self.assertEqual(
                sorted(zf.namelist()),
                sorted([
                    "拿破仑密信__000012.md",
                    "拿破仑密信__000012.mp4",
                    "拿破仑密信__000012.jpg",
                ]),
            )

    def test_legacy_disk_names_are_normalized_inside_bundle(self):
        legacy = dict(self.job)
        legacy["video_title"] = "旧视频"
        for key, ext in (("text_filename", "md"), ("video_filename", "mp4"), ("thumbnail_filename", "jpg")):
            old = self.root / legacy[key]
            old.unlink()
            name = f"wxv_000012.{ext}"
            (self.root / name).write_bytes(b"x")
            legacy[key] = name
        path = ensure_bundle(self.root, legacy)
        with zipfile.ZipFile(path) as zf:
            self.assertEqual(
                sorted(zf.namelist()),
                sorted(["旧视频__000012.md", "旧视频__000012.mp4", "旧视频__000012.jpg"]),
            )

    def test_optional_video_and_thumbnail_may_be_absent(self):
        job = dict(self.job)
        (self.root / job["video_filename"]).unlink()
        (self.root / job["thumbnail_filename"]).unlink()
        job["video_filename"] = None
        job["thumbnail_filename"] = None
        path = ensure_bundle(self.root, job)
        with zipfile.ZipFile(path) as zf:
            self.assertEqual(zf.namelist(), ["拿破仑密信__000012.md"])

    def test_cache_reused_then_invalidated_when_component_changes(self):
        path = ensure_bundle(self.root, self.job)
        first_mtime = path.stat().st_mtime_ns
        same = ensure_bundle(self.root, self.job)
        self.assertEqual(same.stat().st_mtime_ns, first_mtime)
        time.sleep(0.01)
        text = self.root / self.job["text_filename"]
        text.write_text("changed", "utf-8")
        os.utime(text, None)
        rebuilt = ensure_bundle(self.root, self.job)
        self.assertGreater(rebuilt.stat().st_mtime_ns, first_mtime)

    def test_cache_invalidated_when_expected_member_set_changes(self):
        path = ensure_bundle(self.root, self.job)
        first_mtime = path.stat().st_mtime_ns
        time.sleep(0.01)
        job = dict(self.job)
        job["thumbnail_filename"] = None
        rebuilt = ensure_bundle(self.root, job)
        self.assertGreater(rebuilt.stat().st_mtime_ns, first_mtime)
        with zipfile.ZipFile(rebuilt) as zf:
            self.assertNotIn("拿破仑密信__000012.jpg", zf.namelist())

    def test_rejects_traversal_db_filename(self):
        job = dict(self.job)
        job["text_filename"] = "../../secret.md"
        job["video_filename"] = None
        job["thumbnail_filename"] = None
        with self.assertRaises(FileNotFoundError):
            ensure_bundle(self.root, job)

    def test_temp_zip_is_cleaned_on_failure(self):
        with patch("server_docker.bundle_service.zipfile.ZipFile", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                ensure_bundle(self.root, self.job)
        self.assertEqual(list(self.root.glob("*.tmp")), [])
        self.assertEqual(list(self.root.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
