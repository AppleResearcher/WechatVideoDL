import tempfile
import unittest
from pathlib import Path

from server_docker.history_store import HistoryStore
from server_docker.job_runner import is_retryable_error, run_parse_job


class FakeError(RuntimeError):
    def __init__(self, code, message="boom", status=502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class JobRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.downloads = root / "downloads"
        self.store = HistoryStore(root / "history.db")
        self.job_id = "wxv_000101"
        self.store.create_job(
            id=self.job_id,
            input_url="https://weixin.qq.com/sph/demo",
            prompt="summary",
            preset_id=None,
            preset_name=None,
            output_format="md",
            download_requested=True,
            max_attempts=3,
        )

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def success_analysis():
        return {
            "content": "result",
            "previewUrl": "https://channels.weixin.qq.com/finder-preview/demo",
            "directUrl": "https://finder.video.qq.com/demo.mp4",
            "card": {"title": "演示视频", "coverUrl": "https://img.example.com/cover.jpg"},
        }

    def downloader(self, output_stem, direct_url, referer):
        self.downloads.mkdir(parents=True, exist_ok=True)
        p = self.downloads / f"{output_stem}.mp4"
        p.write_bytes(b"video")
        return p

    def _run_job(self, analyzer, downloader=None, sleeper=None, thumbnailer=None):
        return run_parse_job(
            self.job_id,
            "https://weixin.qq.com/sph/demo",
            "summary",
            None,
            "md",
            True,
            store=self.store,
            download_dir=self.downloads,
            analyzer=analyzer,
            downloader=downloader or self.downloader,
            max_attempts=3,
            sleeper=sleeper or (lambda _: None),
            thumbnailer=thumbnailer,
        )

    def test_retryable_success_on_second_attempt(self):
        calls = []
        def analyzer(url, prompt):
            calls.append(1)
            if len(calls) == 1:
                raise FakeError("BROWSERLESS_UNREACHABLE")
            return self.success_analysis()

        row = self._run_job(analyzer)
        self.assertEqual(len(calls), 2)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["attempts_used"], 2)
        self.assertEqual(len(row["retry_errors"]), 1)
        self.assertEqual(row["retry_errors"][0]["code"], "BROWSERLESS_UNREACHABLE")
        self.assertEqual(row["video_title"], "演示视频")
        self.assertEqual(row["cover_url"], "https://img.example.com/cover.jpg")
        self.assertEqual(row["text_filename"], "演示视频__000101.md")
        self.assertEqual(row["video_filename"], "演示视频__000101.mp4")

    def test_retryable_success_on_third_attempt_and_backoff(self):
        calls, sleeps = [], []
        def analyzer(url, prompt):
            calls.append(1)
            if len(calls) < 3:
                raise FakeError("VIDEO_URL_MISSING")
            return self.success_analysis()

        row = self._run_job(analyzer, sleeper=sleeps.append)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [1, 2])
        self.assertEqual(row["attempts_used"], 3)
        self.assertEqual(row["status"], "completed")

    def test_non_retryable_error_stops_immediately(self):
        calls = []
        def analyzer(url, prompt):
            calls.append(1)
            raise FakeError("YUANBAO_LOGIN_REQUIRED", status=401)

        row = self._run_job(analyzer)
        self.assertEqual(len(calls), 1)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempts_used"], 1)
        self.assertEqual(row["error_code"], "YUANBAO_LOGIN_REQUIRED")

    def test_final_transient_failure_persists_one_row(self):
        def analyzer(url, prompt):
            raise FakeError("BROWSERLESS_ERROR")

        row = self._run_job(analyzer)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempts_used"], 3)
        self.assertEqual(len(row["retry_errors"]), 3)
        self.assertEqual(len(self.store.list_jobs()), 1)

    def test_partial_artifacts_are_removed_before_retry(self):
        downloads = []
        analysis_calls = []
        neighbor = self.downloads / "第一个标题__000202.mp4"
        self.downloads.mkdir(parents=True, exist_ok=True)
        neighbor.write_bytes(b"neighbor")

        def analyzer(url, prompt):
            analysis_calls.append(1)
            title = "第一个标题" if len(analysis_calls) == 1 else "第二个标题"
            return {
                "content": "result",
                "previewUrl": "https://channels.weixin.qq.com/finder-preview/demo",
                "directUrl": "https://finder.video.qq.com/demo.mp4",
                "card": {"title": title, "coverUrl": ""},
            }

        def downloader(output_stem, direct_url, referer):
            partial = self.downloads / f"{output_stem}.mp4"
            partial.write_bytes(b"partial")
            downloads.append(partial)
            if len(downloads) == 1:
                raise FakeError("DOWNLOAD_FAILED")
            partial.write_bytes(b"final")
            return partial

        row = self._run_job(analyzer, downloader=downloader)
        self.assertEqual(row["status"], "completed")
        self.assertFalse((self.downloads / "第一个标题__000101.md").exists())
        self.assertFalse((self.downloads / "第一个标题__000101.mp4").exists())
        self.assertEqual((self.downloads / "第二个标题__000101.mp4").read_bytes(), b"final")
        self.assertTrue((self.downloads / "第二个标题__000101.md").exists())
        self.assertTrue(neighbor.exists())

    def test_retry_attempts_are_capped_at_three(self):
        calls = []
        def analyzer(url, prompt):
            calls.append(1)
            raise FakeError("BROWSERLESS_ERROR")

        row = run_parse_job(
            self.job_id,
            "https://weixin.qq.com/sph/demo",
            "summary",
            None,
            "md",
            True,
            store=self.store,
            download_dir=self.downloads,
            analyzer=analyzer,
            downloader=self.downloader,
            max_attempts=10,
            sleeper=lambda _: None,
        )
        self.assertEqual(len(calls), 3)
        self.assertEqual(row["attempts_used"], 3)
        self.assertEqual(row["max_attempts"], 3)

    def test_retry_classifier(self):
        self.assertTrue(is_retryable_error(FakeError("BROWSERLESS_UNREACHABLE")))
        self.assertTrue(is_retryable_error(FakeError("DOWNLOAD_TIMEOUT", status=504)))
        self.assertFalse(is_retryable_error(FakeError("INVALID_URL", status=400)))
        self.assertFalse(is_retryable_error(FakeError("YUANBAO_LOGIN_REQUIRED", status=401)))

    def test_thumbnail_success_is_persisted_with_shared_stem(self):
        def thumbnailer(download_dir, target_filename, cover_url, video_path):
            self.assertEqual(target_filename, "演示视频__000101.jpg")
            self.assertEqual(cover_url, "https://img.example.com/cover.jpg")
            self.assertEqual(video_path.name, "演示视频__000101.mp4")
            path = download_dir / target_filename
            path.write_bytes(b"jpg")
            return path
        row = self._run_job(lambda *_: self.success_analysis(), thumbnailer=thumbnailer)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["thumbnail_filename"], "演示视频__000101.jpg")

    def test_thumbnail_exception_does_not_fail_completed_job(self):
        def thumbnailer(*args, **kwargs):
            raise RuntimeError("thumbnail failed")
        row = self._run_job(lambda *_: self.success_analysis(), thumbnailer=thumbnailer)
        self.assertEqual(row["status"], "completed")
        self.assertIsNone(row["thumbnail_filename"])


if __name__ == "__main__":
    unittest.main()
