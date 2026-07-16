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


if __name__ == "__main__":
    unittest.main()
