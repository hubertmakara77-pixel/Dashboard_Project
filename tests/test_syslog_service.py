import datetime
import gzip
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from app.core import config
from app.services import syslog as syslog_service


class SyslogServiceTests(unittest.TestCase):
    def test_message_is_sent_to_system_syslog_over_udp(self):
        with (
            mock.patch.object(config, "SYSLOG_ENABLED", True),
            mock.patch("app.services.syslog.socket.socket") as socket_mock,
        ):
            syslog_service.send_syslog("changed=value", syslog_service.SEVERITY_INFO)

        sendto = socket_mock.return_value.__enter__.return_value.sendto
        sendto.assert_called_once()
        payload, destination = sendto.call_args.args
        self.assertIn(
            f"amp-dashboard: device={config.DEVICE_NAME}; changed=value".encode(),
            payload,
        )
        self.assertEqual(destination, (config.SYSLOG_HOST, config.SYSLOG_PORT))

    def test_disabled_syslog_does_not_send(self):
        with (
            mock.patch.object(config, "SYSLOG_ENABLED", False),
            mock.patch("app.services.syslog.socket.socket") as socket_mock,
        ):
            syslog_service.send_syslog("ignored", syslog_service.SEVERITY_INFO)

        socket_mock.assert_not_called()

    def test_audit_uses_syslog_header_time_without_duplicate_message_timestamp(self):
        fixed_time = datetime.datetime(
            2026, 7, 16, 23, 15, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2))
        )
        with (
            mock.patch.object(config, "SYSLOG_ENABLED", True),
            mock.patch("app.services.syslog.local_now", return_value=fixed_time),
            mock.patch("app.services.syslog.socket.socket") as socket_mock,
        ):
            syslog_service.send_audit("settings_updated", "admin", "127.0.0.1")

        payload = socket_mock.return_value.__enter__.return_value.sendto.call_args.args[0]
        self.assertIn(b"Jul 16 23:15:00", payload)
        self.assertIn(
            f"amp-dashboard: device={config.DEVICE_NAME}; audit; user=admin".encode(),
            payload,
        )
        self.assertNotIn(b"audit timestamp=", payload)

    def test_warning_relies_on_syslog_header_timestamp(self):
        with (
            mock.patch.object(config, "SYSLOG_ENABLED", True),
            mock.patch("app.services.syslog.socket.socket") as socket_mock,
        ):
            syslog_service.send_warning("WARNING field=PiA")

        payload = socket_mock.return_value.__enter__.return_value.sendto.call_args.args[0]
        self.assertIn(
            f"amp-dashboard: device={config.DEVICE_NAME}; warning; WARNING field=PiA".encode(),
            payload,
        )
        self.assertNotIn(b"warning timestamp=", payload)

    def test_structured_warning_event_is_sent_as_json(self):
        warning = {
            "time": "2026-07-25T12:00:00+00:00",
            "field": "temperature",
            "kind": "max",
            "label": "Temperature",
            "value": 51.5,
            "target": 50.0,
            "delta": 1.5,
            "message": "Temperature above MAX threshold 50.00",
        }
        with (
            mock.patch.object(config, "SYSLOG_ENABLED", True),
            mock.patch("app.services.syslog.socket.socket") as socket_mock,
        ):
            syslog_service.send_warning_event("OPEN", warning)

        payload = socket_mock.return_value.__enter__.return_value.sendto.call_args.args[0]
        encoded_event = payload.decode().split("; warning; ", 1)[1]
        event = json.loads(encoded_event)
        self.assertEqual(event["event"], "OPEN")
        self.assertEqual(event["field"], "temperature")
        self.assertEqual(event["value"], 51.5)

    def test_warning_history_reads_current_and_rotated_gzip_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = pathlib.Path(directory) / "amp-dashboard.log"
            open_event = {
                "event": "OPEN",
                "event_time": "2026-07-25T12:00:00+00:00",
                "field": "temperature",
                "kind": "max",
                "label": "Temperature",
                "value": 51.5,
                "target": 50.0,
                "delta": 1.5,
                "message": "Too hot",
            }
            cleared_event = {
                **open_event,
                "event": "CLEARED",
                "event_time": "2026-07-25T12:05:00+00:00",
                "value": 49.0,
                "duration_seconds": 300,
            }
            log_path.write_text(
                "2026-07-25T12:05:00+00:00 amp-dashboard: "
                f"device=test; warning; {json.dumps(cleared_event)}\n",
                encoding="utf-8",
            )
            with gzip.open(f"{log_path}.1.gz", "wt", encoding="utf-8") as stream:
                stream.write(
                    "2026-07-25T12:00:00+00:00 amp-dashboard: "
                    f"device=test; warning; {json.dumps(open_event)}\n"
                )

            with mock.patch.object(config, "SYSLOG_EXPORT_FILE", str(log_path)):
                history = syslog_service.read_warning_history(
                    start=datetime.datetime(
                        2026, 7, 25, 11, 0, tzinfo=datetime.timezone.utc
                    ),
                    status="cleared",
                )

        self.assertEqual(history["total"], 1)
        self.assertEqual(history["events"][0]["event"], "CLEARED")
        self.assertEqual(history["events"][0]["duration_seconds"], 300)

    def test_legacy_warning_line_remains_visible(self):
        event = syslog_service.parse_warning_log_line(
            "2026-07-25T12:00:00+00:00 amp-dashboard: "
            'device=test; warning; WARNING field=PiA kind=min value=-30 '
            'threshold=-25 delta=-5 message="PiA below limit"\n'
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["event"], "OPEN")
        self.assertEqual(event["field"], "PiA")
        self.assertEqual(event["message"], "PiA below limit")

    def test_lifecycle_event_contains_event_and_fields(self):
        with (
            mock.patch.object(config, "SYSLOG_ENABLED", True),
            mock.patch("app.services.syslog.socket.socket") as socket_mock,
        ):
            syslog_service.send_lifecycle(
                "heartbeat",
                database="ready",
                stored_records=12,
            )

        payload = socket_mock.return_value.__enter__.return_value.sendto.call_args.args[0]
        self.assertIn(
            b"lifecycle; event=heartbeat; database=ready; stored_records=12",
            payload,
        )


if __name__ == "__main__":
    unittest.main()
