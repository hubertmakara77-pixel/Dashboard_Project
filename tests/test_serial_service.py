import sys
import unittest
from unittest import mock

from app.core import state

sys.modules.setdefault("serial", mock.MagicMock())
sys.modules.setdefault("app.services.snmp", mock.MagicMock())
from app.services import serial as serial_service


class SerialWarningTests(unittest.TestCase):
    def test_temperature_threshold_creates_warning(self):
        settings = state.merge_dashboard_settings({
            "warn_limits": {
                "temperature": {"min": 10.0, "max": 50.0},
            },
        })

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


if __name__ == "__main__":
    unittest.main()
