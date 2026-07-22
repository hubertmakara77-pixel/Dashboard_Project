import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import database_service
import state


class DatabaseServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_settings = state.service_settings.copy()
        self.original_discarded = database_service.discarded_records
        database_service.close_database()
        database_service.discarded_records = 0
        self.database_patch = mock.patch.object(
            config,
            "DATABASE_FILE",
            str(Path(self.temp_dir.name) / "measurements.db"),
        )
        self.database_patch.start()
        state.service_settings["database_max_records"] = 100

    def tearDown(self):
        database_service.close_database()
        database_service.discarded_records = self.original_discarded
        state.service_settings.clear()
        state.service_settings.update(self.original_settings)
        self.database_patch.stop()
        self.temp_dir.cleanup()

    def test_measurement_survives_database_reopen(self):
        timestamp = "2026-07-17T10:15:30+00:00"
        self.assertTrue(database_service.write_measurement({"PiA": 1.0}, timestamp))
        database_service.close_database()
        database_service.init_database()

        self.assertEqual(database_service.get_record_count(), 1)
        row = database_service.connection.execute(
            "SELECT measurement, timestamp, fields_json FROM measurements"
        ).fetchone()
        self.assertEqual(row["measurement"], config.MEASUREMENT_NAME)
        self.assertEqual(row["timestamp"], timestamp)
        self.assertIn('"PiA":1.0', row["fields_json"])

    def test_record_limit_discards_oldest_measurement(self):
        state.service_settings["database_max_records"] = 2
        with mock.patch("database_service.syslog_service.send_warning") as warning_mock:
            for second in range(3):
                database_service.write_measurement(
                    {"PiA": float(second)},
                    f"2026-07-17T10:15:3{second}+00:00",
                )

        rows = database_service.connection.execute(
            "SELECT timestamp FROM measurements ORDER BY id"
        ).fetchall()
        self.assertEqual(
            [row["timestamp"] for row in rows],
            ["2026-07-17T10:15:31+00:00", "2026-07-17T10:15:32+00:00"],
        )
        warning_mock.assert_called_once()
        self.assertEqual(database_service.discarded_records, 1)

    def test_updated_limit_prunes_oldest_records_immediately(self):
        for second in range(3):
            database_service.write_measurement(
                {"PiA": float(second)},
                f"2026-07-17T10:15:3{second}+00:00",
            )
        state.service_settings["database_max_records"] = 1

        self.assertEqual(database_service.apply_record_limit(), 2)
        self.assertEqual(database_service.get_record_count(), 1)

    def test_history_is_read_and_aggregated_from_sqlite(self):
        database_service.write_measurement(
            {"PiA": 1.0, "PoA": 3.0}, "2026-07-17T10:15:30+00:00"
        )
        database_service.write_measurement(
            {"PiA": 3.0, "PoA": 5.0}, "2026-07-17T10:15:30.500000+00:00"
        )

        points = database_service.query_history(
            "5m",
            start="2026-07-17T10:15:00+00:00",
            end="2026-07-17T10:16:00+00:00",
        )

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["PiA"], 2.0)
        self.assertEqual(points[0]["PoA"], 4.0)

    def test_setpoint_is_stored_as_separate_measurement(self):
        database_service.write_setpoint(12.5, "2026-07-17T10:15:30+00:00")
        row = database_service.connection.execute(
            "SELECT measurement, fields_json FROM measurements"
        ).fetchone()
        self.assertEqual(row["measurement"], config.SETPOINT_MEASUREMENT_NAME)
        self.assertIn('"gain_set":12.5', row["fields_json"])

    def test_runtime_status_reports_ready_database(self):
        database_service.write_measurement(
            {"PiA": 1.0}, "2026-07-17T10:15:30+00:00"
        )
        status = database_service.get_runtime_status()
        self.assertEqual(status["state"], "ready")
        self.assertTrue(status["ready"])
        self.assertEqual(status["records"], 1)


if __name__ == "__main__":
    unittest.main()
