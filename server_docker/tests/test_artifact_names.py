import unittest

from server_docker.artifact_names import artifact_filename, artifact_stem


class ArtifactNameTests(unittest.TestCase):
    def test_preserves_cjk_and_emoji_and_appends_job_suffix(self):
        self.assertEqual(
            artifact_stem("拿破仑密信 🔐", "wxv_000012"),
            "拿破仑密信 🔐__000012",
        )

    def test_replaces_path_and_windows_invalid_characters(self):
        value = artifact_stem('  A/B\\C:D*E?F"G<H>I|J  ', "wxv_000013")
        self.assertEqual(value, "A-B-C-D-E-F-G-H-I-J__000013")

    def test_removes_control_dot_segments_and_trailing_dots(self):
        value = artifact_stem("..  demo\x00\n title...  ", "wxv_000014")
        self.assertEqual(value, "demo title__000014")

    def test_empty_title_falls_back_to_wechat_video(self):
        self.assertEqual(artifact_stem("  ... ", "wxv_000015"), "微信视频号__000015")
        self.assertEqual(artifact_stem(None, "wxv_000016"), "微信视频号__000016")

    def test_reserved_windows_basename_is_prefixed(self):
        self.assertEqual(artifact_stem("CON", "wxv_000017"), "_CON__000017")
        self.assertEqual(artifact_stem("nul.txt", "wxv_000018"), "_nul.txt__000018")

    def test_utf8_truncation_is_byte_safe(self):
        stem = artifact_stem("猫😀" * 100, "wxv_000019", max_stem_bytes=80)
        self.assertLessEqual(len(stem.encode("utf-8")), 80)
        self.assertTrue(stem.endswith("__000019"))
        stem.encode("utf-8").decode("utf-8")

    def test_same_title_different_job_ids_do_not_collide(self):
        self.assertNotEqual(
            artifact_stem("同名视频", "wxv_000020"),
            artifact_stem("同名视频", "wxv_000021"),
        )

    def test_filename_validates_extension(self):
        self.assertEqual(
            artifact_filename("标题", "wxv_000022", "mp4"),
            "标题__000022.mp4",
        )
        with self.assertRaises(ValueError):
            artifact_filename("标题", "wxv_000022", "exe")

    def test_invalid_job_id_is_rejected(self):
        with self.assertRaises(ValueError):
            artifact_stem("标题", "not-a-job")


if __name__ == "__main__":
    unittest.main()
