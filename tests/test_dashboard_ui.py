import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class DashboardUiTests(unittest.TestCase):
    def test_system_time_comes_from_latest_api_response(self):
        script = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

        self.assertIn("formatTime(json.system_time)", script)
        self.assertNotIn(
            "setTextIfExists('status-system-time', new Date().toLocaleTimeString())",
            script,
        )


if __name__ == "__main__":
    unittest.main()
