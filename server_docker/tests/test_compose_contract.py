import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ComposeContractTests(unittest.TestCase):
    def test_async_queue_settings_are_forwarded_to_app_container(self):
        compose = (ROOT / "docker-compose.yml").read_text("utf-8")
        self.assertIn("MAX_PENDING_JOBS: ${MAX_PENDING_JOBS:-8}", compose)
        self.assertIn("POLL_INTERVAL_SECONDS: ${POLL_INTERVAL_SECONDS:-3}", compose)


if __name__ == "__main__":
    unittest.main()
