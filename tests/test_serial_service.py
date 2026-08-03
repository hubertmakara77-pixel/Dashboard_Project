import sys
import unittest
from unittest import mock

from app.core import state

sys.modules.setdefault("serial", mock.MagicMock())
sys.modules.setdefault("app.services.snmp", mock.MagicMock())
from app.services import serial as serial_service


class SerialWarningTests(unittest.TestCase):
    def test_temperature_threshold_creates_warning(self):
        settings = state.merge_dashboard_settings(
            {
                "warn_limits": {
                    "temperature": {"min": 10.0, "max": 50.0},
                },
            }
        )

        with mock.patch.object(state, "dashboard_settings", settings):
            errors = serial_service.build_limit_errors(
                {"temperature": 51.5},
                "2026-07-23T10:00:00+00:00",
            )

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["field"], "temperature")
        self.assertEqual(errors[0]["kind"], "max")
        self.assertEqual(errors[0]["target"], 50.0)
        self.assertEqual(errors[0]["value"], 51.5)

    def test_warning_state_emits_one_open_and_one_cleared_event(self):
        warning = {
            "time": "2026-07-25T12:00:00+00:00",
            "field": "temperature",
            "kind": "max",
            "label": "Temperature",
            "value": 51.5,
            "target": 50.0,
            "delta": 1.5,
            "allowed": 0,
            "message": "Temperature above MAX threshold 50.00",
        }
        with (
            mock.patch.object(state, "active_warnings", {}),
            mock.patch.object(state, "acknowledged_warning_keys", set()),
        ):
            opened, cleared = serial_service.update_warning_state(
                [warning], "2026-07-25T12:00:00+00:00"
            )
            repeated_opened, repeated_cleared = serial_service.update_warning_state(
                [{**warning, "value": 52.0}],
                "2026-07-25T12:00:05+00:00",
            )
            final_opened, final_cleared = serial_service.update_warning_state(
                [],
                "2026-07-25T12:00:10+00:00",
                {"temperature": 49.0},
            )

        self.assertEqual(len(opened), 1)
        self.assertEqual(cleared, [])
        self.assertEqual(repeated_opened, [])
        self.assertEqual(repeated_cleared, [])
        self.assertEqual(final_opened, [])
        self.assertEqual(len(final_cleared), 1)
        self.assertEqual(final_cleared[0]["event"], "CLEARED")
        self.assertEqual(final_cleared[0]["duration_seconds"], 10.0)
        self.assertEqual(final_cleared[0]["value"], 49.0)
        self.assertEqual(final_cleared[0]["delta"], -1.0)


if __name__ == "__main__":
    unittest.main()
