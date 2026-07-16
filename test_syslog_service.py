import datetime
import pathlib
import tempfile
import unittest
from unittest import mock

import config
import syslog_service


class SyslogServiceTests(unittest.TestCase):
    def test_message_is_saved_locally_and_sent_over_udp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "syslog.log"
            with (
                mock.patch.object(config, "SYSLOG_ENABLED", True),
                mock.patch.object(config, "SYSLOG_LOG_FILE", str(path)),
                mock.patch("syslog_service.socket.socket") as socket_mock,
            ):
                syslog_service.send_syslog("changed=value", syslog_service.SEVERITY_INFO)

            content = path.read_text(encoding="utf-8")
            self.assertIn("amp-dashboard: changed=value", content)
            socket_mock.return_value.__enter__.return_value.sendto.assert_called_once()

    def test_disabled_syslog_does_not_write_or_send(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "syslog.log"
            with (
                mock.patch.object(config, "SYSLOG_ENABLED", False),
                mock.patch.object(config, "SYSLOG_LOG_FILE", str(path)),
                mock.patch("syslog_service.socket.socket") as socket_mock,
            ):
                syslog_service.send_syslog("ignored", syslog_service.SEVERITY_INFO)

            self.assertFalse(path.exists())
            socket_mock.assert_not_called()

    def test_audit_uses_configured_local_time_with_offset(self):
        fixed_time = datetime.datetime(
            2026, 7, 16, 23, 15, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2))
        )
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "syslog.log"
            with (
                mock.patch.object(config, "SYSLOG_ENABLED", True),
                mock.patch.object(config, "SYSLOG_LOG_FILE", str(path)),
                mock.patch("syslog_service.local_now", return_value=fixed_time),
                mock.patch("syslog_service.socket.socket"),
            ):
                syslog_service.send_audit("settings_updated", "admin", "127.0.0.1")

            content = path.read_text(encoding="utf-8")
            self.assertIn("Jul 16 23:15:00", content)
            self.assertIn("timestamp=2026-07-16T23:15:00+02:00", content)


if __name__ == "__main__":
    unittest.main()
