import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import influx_service
import state


class FakePoint:
    timestamps = []

    def __init__(self, measurement):
        self.measurement = measurement

    def tag(self, *_args):
        return self

    def field(self, *_args):
        return self

    def time(self, timestamp):
        self.timestamps.append(timestamp)
        return self


class FakeInfluxModule:
    Point = FakePoint


class FailingApi:
    def write(self, **_kwargs):
        raise ConnectionError("database unavailable")

    def query(self, *_args, **_kwargs):
        raise ConnectionError("database unavailable")


class SuccessfulApi:
    def __init__(self):
        self.records = []

    def write(self, **kwargs):
        self.records.append(kwargs["record"])


class FakeClient:
    def close(self):
        pass


class InfluxResilienceTests(unittest.TestCase):
    def setUp(self):
        FakePoint.timestamps.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.originals = (
            influx_service.influxdb_client,
            influx_service.client,
            influx_service.write_api,
            influx_service.query_api,
            influx_service.buffer_connection,
            influx_service.next_reconnect_at,
            influx_service.buffer_discarded_records,
            influx_service.last_error_log.copy(),
            state.service_settings.copy(),
        )
        self.config_patches = (
            mock.patch.object(
                config,
                "INFLUX_BUFFER_FILE",
                str(Path(self.temp_dir.name) / "influx-buffer.db"),
            ),
            mock.patch.object(config, "INFLUX_BUFFER_MAX_RECORDS", 100),
            mock.patch.object(config, "INFLUX_BUFFER_BATCH_SIZE", 10),
            mock.patch.object(config, "INFLUX_RETRY_SECONDS", 1),
        )
        for patcher in self.config_patches:
            patcher.start()

        state.service_settings["influx_buffer_max_records"] = 100
        state.service_settings["influx_buffer_min_free_mb"] = 0

        influx_service.influxdb_client = FakeInfluxModule()
        influx_service.client = FakeClient()
        influx_service.write_api = FailingApi()
        influx_service.query_api = FailingApi()
        influx_service.buffer_connection = None
        influx_service.next_reconnect_at = 0
        influx_service.buffer_discarded_records = 0
        influx_service.last_error_log.clear()
        influx_service.buffer_stop_event.clear()
        influx_service.buffer_wakeup_event.clear()

    def tearDown(self):
        if influx_service.buffer_connection is not None:
            influx_service.buffer_connection.close()
        (
            influx_service.influxdb_client,
            influx_service.client,
            influx_service.write_api,
            influx_service.query_api,
            influx_service.buffer_connection,
            influx_service.next_reconnect_at,
            influx_service.buffer_discarded_records,
            original_last_error_log,
            original_service_settings,
        ) = self.originals
        influx_service.last_error_log.clear()
        influx_service.last_error_log.update(original_last_error_log)
        state.service_settings.clear()
        state.service_settings.update(original_service_settings)
        for patcher in reversed(self.config_patches):
            patcher.stop()
        self.temp_dir.cleanup()

    def test_failed_flush_keeps_measurement_on_disk(self):
        influx_service.write_measurement({"PiA": 1.0}, "2026-07-17T10:15:30+00:00")

        self.assertEqual(influx_service.get_pending_record_count(), 1)
        self.assertEqual(influx_service.flush_influx_buffer(), 0)
        self.assertEqual(influx_service.get_pending_record_count(), 1)
        self.assertIsNone(influx_service.client)

    def test_successful_flush_removes_record_and_preserves_timestamp(self):
        timestamp = "2026-07-17T10:15:30+00:00"
        influx_service.write_measurement({"PiA": 1.0}, timestamp)
        successful_api = SuccessfulApi()
        influx_service.client = FakeClient()
        influx_service.write_api = successful_api
        influx_service.query_api = successful_api

        self.assertEqual(influx_service.flush_influx_buffer(), 1)
        self.assertEqual(influx_service.get_pending_record_count(), 0)
        self.assertEqual(FakePoint.timestamps, [timestamp])
        self.assertEqual(len(successful_api.records), 1)

    def test_queue_survives_database_reopen(self):
        influx_service.write_setpoint(12.5, "2026-07-17T10:15:30+00:00")
        influx_service.buffer_connection.close()
        influx_service.buffer_connection = None

        influx_service.init_influx_buffer()

        self.assertEqual(influx_service.get_pending_record_count(), 1)
        row = influx_service.buffer_connection.execute(
            "SELECT measurement, fields_json FROM pending_influx_records"
        ).fetchone()
        self.assertEqual(row["measurement"], config.SETPOINT_MEASUREMENT_NAME)
        self.assertIn('"gain_set":12.5', row["fields_json"])

    def test_buffer_discards_oldest_record_at_configured_limit(self):
        state.service_settings["influx_buffer_max_records"] = 2
        with mock.patch("influx_service.syslog_service.send_warning") as warning_mock:
            influx_service.write_measurement({"PiA": 1.0}, "one")
            influx_service.write_measurement({"PiA": 2.0}, "two")
            influx_service.write_measurement({"PiA": 3.0}, "three")

        rows = influx_service.buffer_connection.execute(
            "SELECT timestamp FROM pending_influx_records ORDER BY id"
        ).fetchall()
        self.assertEqual([row["timestamp"] for row in rows], ["two", "three"])
        warning_mock.assert_called_once()
        self.assertEqual(influx_service.buffer_discarded_records, 1)

    def test_updated_limit_prunes_oldest_records_immediately(self):
        for index in range(3):
            influx_service.write_measurement({"PiA": float(index)}, str(index))
        state.service_settings["influx_buffer_max_records"] = 1

        self.assertEqual(influx_service.apply_buffer_limits(), 2)
        rows = influx_service.buffer_connection.execute(
            "SELECT timestamp FROM pending_influx_records ORDER BY id"
        ).fetchall()
        self.assertEqual([row["timestamp"] for row in rows], ["2"])

    def test_disk_reserve_prevents_buffer_growth(self):
        state.service_settings["influx_buffer_min_free_mb"] = 512
        disk_status = mock.Mock(free=100 * 1024 * 1024)
        with (
            mock.patch("influx_service.shutil.disk_usage", return_value=disk_status),
            mock.patch("influx_service.syslog_service.send_warning") as warning_mock,
        ):
            influx_service.write_measurement({"PiA": 1.0}, "one")

        self.assertEqual(influx_service.get_pending_record_count(), 0)
        self.assertEqual(influx_service.buffer_discarded_records, 1)
        warning_mock.assert_called_once()

    def test_runtime_status_distinguishes_syncing_and_buffering(self):
        self.assertEqual(influx_service.get_runtime_status()["state"], "connected")
        influx_service.write_measurement({"PiA": 1.0}, "one")
        self.assertEqual(influx_service.get_runtime_status()["state"], "syncing")
        influx_service.client = None
        influx_service.write_api = None
        influx_service.query_api = None
        status = influx_service.get_runtime_status()
        self.assertEqual(status["state"], "buffering")
        self.assertEqual(status["pending_records"], 1)

    def test_query_failure_falls_back_to_memory(self):
        result = influx_service.query_history_from_influx("5m")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
