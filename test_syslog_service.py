import datetime
import unittest
from unittest import mock

import config
import syslog_service


class SyslogServiceTests(unittest.TestCase):
    def test_message_is_sent_to_system_syslog_over_udp(self):
        with (
            mock.patch.object(config, "SYSLOG_ENABLED", True),
            mock.patch("syslog_service.socket.socket") as socket_mock,
        ):
            syslog_service.send_syslog("changed=value", syslog_service.SEVERITY_INFO)

        sendto = socket_mock.return_value.__enter__.return_value.sendto
        sendto.assert_called_once()
        payload, destination = sendto.call_args.args
        self.assertIn(b"amp-dashboard: changed=value", payload)
        self.assertEqual(destination, (config.SYSLOG_HOST, config.SYSLOG_PORT))

    def test_disabled_syslog_does_not_send(self):
        with (
            mock.patch.object(config, "SYSLOG_ENABLED", False),
            mock.patch("syslog_service.socket.socket") as socket_mock,
        ):
            syslog_service.send_syslog("ignored", syslog_service.SEVERITY_INFO)

        socket_mock.assert_not_called()

    def test_audit_uses_syslog_header_time_without_duplicate_message_timestamp(self):
        fixed_time = datetime.datetime(
            2026, 7, 16, 23, 15, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2))
        )
        with (
            mock.patch.object(config, "SYSLOG_ENABLED", True),
            mock.patch("syslog_service.local_now", return_value=fixed_time),
            mock.patch("syslog_service.socket.socket") as socket_mock,
        ):
            syslog_service.send_audit("settings_updated", "admin", "127.0.0.1")

        payload = socket_mock.return_value.__enter__.return_value.sendto.call_args.args[0]
        self.assertIn(b"Jul 16 23:15:00", payload)
        self.assertIn(b"amp-dashboard: audit; user=admin", payload)
        self.assertNotIn(b"audit timestamp=", payload)

    def test_warning_relies_on_syslog_header_timestamp(self):
        with (
            mock.patch.object(config, "SYSLOG_ENABLED", True),
            mock.patch("syslog_service.socket.socket") as socket_mock,
        ):
            syslog_service.send_warning("WARNING field=PiA")

        payload = socket_mock.return_value.__enter__.return_value.sendto.call_args.args[0]
        self.assertIn(b"amp-dashboard: warning; WARNING field=PiA", payload)
        self.assertNotIn(b"warning timestamp=", payload)


if __name__ == "__main__":
    unittest.main()
