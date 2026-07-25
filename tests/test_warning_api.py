import unittest
from unittest import mock

from app.core import state

try:
    from app.api import dashboard
except ModuleNotFoundError:
    dashboard = None

@unittest.skipIf(dashboard is None, "FastAPI is not installed in this test runtime")
class WarningApiTests(unittest.TestCase):
    def test_warning_history_uses_requested_filters(self):
        history = {
            "events": [{"event": "OPEN", "field": "temperature"}],
            "total": 1,
            "offset": 0,
            "limit": 25,
            "source_available": True,
            "unreadable_files": 0,
        }
        with mock.patch.object(
            dashboard.syslog_service,
            "read_warning_history",
            return_value=history,
        ) as reader:
            result = dashboard.get_warnings(
                range_value="24h",
                start="",
                end="",
                field="temperature",
                status="open",
                limit=25,
                offset=0,
                _current_user={"role": "Viewer"},
            )

        self.assertEqual(result["history"], history["events"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(reader.call_args.kwargs["field"], "temperature")
        self.assertEqual(reader.call_args.kwargs["status"], "open")

    def test_acknowledge_marks_active_warnings_without_removing_them(self):
        key = ("temperature", "max")
        active = {
            key: {
                "field": "temperature",
                "kind": "max",
                "acknowledged": False,
            }
        }
        with (
            mock.patch.object(state, "active_warnings", active),
            mock.patch.object(state, "acknowledged_warning_keys", set()),
            mock.patch.object(dashboard.api_security, "audit_event") as audit,
        ):
            result = dashboard.acknowledge_warnings(
                request=mock.MagicMock(),
                current_user={"username": "operator", "role": "Operator"},
            )

            self.assertIn(key, state.active_warnings)
            self.assertTrue(state.active_warnings[key]["acknowledged"])

        self.assertEqual(result["acknowledged"], 1)
        audit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
