import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core import config, state
from app.services import database as database_service


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
            "SELECT timestamp_ms, PiA FROM samples"
        ).fetchone()
        self.assertEqual(row["timestamp_ms"], 1784283330000)
        self.assertEqual(row["PiA"], 1.0)

    def test_record_limit_discards_oldest_measurement(self):
        state.service_settings["database_max_records"] = 2
        with mock.patch("app.services.database.syslog_service.send_warning") as warning_mock:
            for second in range(3):
                database_service.write_measurement(
                    {"PiA": float(second)},
                    f"2026-07-17T10:15:3{second}+00:00",
                )

        rows = database_service.connection.execute(
            "SELECT timestamp_ms FROM samples ORDER BY id"
        ).fetchall()
        self.assertEqual(
            [row["timestamp_ms"] for row in rows],
            [1784283331000, 1784283332000],
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

    def test_zero_record_limit_keeps_all_measurements(self):
        state.service_settings["database_max_records"] = 0
        for second in range(3):
            database_service.write_measurement(
                {"PiA": float(second)},
                f"2026-07-17T10:15:3{second}+00:00",
            )

        self.assertEqual(database_service.get_record_count(), 3)
        self.assertEqual(database_service.apply_record_limit(), 0)

    def test_storage_status_estimates_retention_from_recent_write_rate(self):
        for second in range(3):
            database_service.write_measurement(
                {"PiA": float(second)},
                f"2026-07-17T10:15:3{second}+00:00",
            )

        storage = database_service.get_storage_status()

        self.assertEqual(storage["sample_rate_per_second"], 1.0)
        self.assertEqual(storage["estimated_retention_seconds"], 100.0)
        self.assertEqual(storage["estimated_seconds_to_limit"], 97.0)
        self.assertGreater(storage["estimated_seconds_until_disk_full"], 0)

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

        result = database_service.query_history(
            "5m",
            start="2026-07-17T10:15:00+00:00",
            end="2026-07-17T10:16:00+00:00",
            include_metadata=True,
        )
        self.assertEqual(result["sample_count"], 2)
        self.assertEqual(len(result["points"]), 1)
        self.assertEqual(result["aggregation_seconds"], 1)

    def test_history_point_count_is_bounded_for_long_ranges(self):
        with mock.patch.object(config, "HISTORY_MAX_POINTS", 3):
            for second in range(5):
                database_service.write_measurement(
                    {"PiA": float(second)},
                    f"2026-07-17T10:15:{30 + second}+00:00",
                )

            points = database_service.query_history(
                "all",
                start="2026-07-17T10:15:00+00:00",
                end="2026-07-17T10:16:00+00:00",
            )

        self.assertLessEqual(len(points), 3)
        self.assertEqual(sum(point["PiA"] for point in points) / len(points), 2.0)

    def test_statistics_are_calculated_from_raw_samples(self):
        database_service.write_measurement(
            {"PiA": 1.0, "PoA": 10.0}, "2026-07-17T10:15:30+00:00"
        )
        database_service.write_measurement(
            {"PiA": 9.0, "PoA": 12.0}, "2026-07-17T10:15:30.100000+00:00"
        )
        database_service.write_measurement(
            {"PiA": 3.0, "PoA": 16.0}, "2026-07-17T10:15:30.200000+00:00"
        )

        result = database_service.query_statistics(
            "5m",
            start="2026-07-17T10:15:00+00:00",
            end="2026-07-17T10:16:00+00:00",
        )

        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(result["statistics"]["PiA"]["min"], 1.0)
        self.assertEqual(result["statistics"]["PiA"]["max"], 9.0)
        self.assertEqual(result["statistics"]["PiA"]["average"], 13 / 3)
        self.assertAlmostEqual(
            result["statistics"]["PiA"]["standard_deviation"], 3.39934634239519
        )
        self.assertAlmostEqual(
            result["statistics"]["PoA"]["standard_deviation"], 2.494438257849294
        )

    def test_statistics_combine_hourly_summaries_and_raw_boundaries(self):
        samples = (
            ("2026-07-17T10:00:00+00:00", 1.0),
            ("2026-07-17T10:59:59+00:00", 9.0),
            ("2026-07-17T11:00:00+00:00", 3.0),
            ("2026-07-17T11:30:00+00:00", 7.0),
            ("2026-07-17T12:00:00+00:00", 5.0),
        )
        for timestamp, value in samples:
            database_service.write_measurement({"PiA": value}, timestamp)

        summaries = database_service.connection.execute(
            "SELECT bucket_ms FROM hourly_statistics ORDER BY bucket_ms"
        ).fetchall()
        self.assertEqual(len(summaries), 2)

        result = database_service.query_statistics(
            "all",
            start="2026-07-17T10:00:00+00:00",
            end="2026-07-17T12:00:00+00:00",
        )

        self.assertEqual(result["sample_count"], 5)
        self.assertEqual(result["statistics"]["PiA"]["min"], 1.0)
        self.assertEqual(result["statistics"]["PiA"]["max"], 9.0)
        self.assertEqual(result["statistics"]["PiA"]["average"], 5.0)
        self.assertAlmostEqual(
            result["statistics"]["PiA"]["standard_deviation"], 2.8284271247461903
        )

    def test_statistics_keep_exact_custom_range_edges(self):
        samples = (
            ("2026-07-17T10:00:00+00:00", 100.0),
            ("2026-07-17T10:15:00+00:00", 2.0),
            ("2026-07-17T10:45:00+00:00", 6.0),
            ("2026-07-17T11:00:00+00:00", 4.0),
        )
        for timestamp, value in samples:
            database_service.write_measurement({"PiA": value}, timestamp)

        result = database_service.query_statistics(
            "all",
            start="2026-07-17T10:10:00+00:00",
            end="2026-07-17T11:00:00+00:00",
        )

        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(result["statistics"]["PiA"]["min"], 2.0)
        self.assertEqual(result["statistics"]["PiA"]["max"], 6.0)
        self.assertEqual(result["statistics"]["PiA"]["average"], 4.0)
        self.assertAlmostEqual(
            result["statistics"]["PiA"]["standard_deviation"], 1.632993161855452
        )

    def test_existing_database_builds_hourly_summaries_once(self):
        database_service.write_measurement(
            {"PiA": 1.0}, "2026-07-17T10:00:00+00:00"
        )
        database_service.write_measurement(
            {"PiA": 5.0}, "2026-07-17T11:00:00+00:00"
        )
        database_service.connection.execute("DELETE FROM hourly_statistics")
        database_service.connection.execute("PRAGMA user_version=3")
        database_service.connection.commit()
        database_service.close_database()

        database_service.init_database()

        summary = database_service.connection.execute(
            "SELECT sample_count, statistics_json FROM hourly_statistics"
        ).fetchone()
        self.assertIsNotNone(summary)
        self.assertEqual(summary["sample_count"], 1)
        self.assertEqual(
            database_service.json.loads(summary["statistics_json"])["PiA"]["max"],
            1.0,
        )
        self.assertEqual(
            database_service.connection.execute("PRAGMA user_version").fetchone()[0],
            5,
        )

    def test_fts_ls_snapshots_are_stored_pruned_and_queried(self):
        state.service_settings["database_max_records"] = 2
        for second in range(3):
            self.assertTrue(database_service.write_device_snapshot(
                "fts-ls",
                {"laser": {"frequency": 194400 + second}},
                f"2026-07-17T10:15:3{second}+00:00",
            ))

        self.assertEqual(database_service.get_device_snapshot_count("fts-ls"), 2)
        points = database_service.query_device_snapshots(
            "fts-ls",
            "all",
            start="2026-07-17T10:00:00+00:00",
        )
        self.assertEqual(
            [point["snapshot"]["laser"]["frequency"] for point in points],
            [194401, 194402],
        )

    def test_fts_ls_history_is_evenly_downsampled_across_selected_range(self):
        state.service_settings["database_max_records"] = 0
        for second in range(10):
            database_service.write_device_snapshot(
                "fts-ls",
                {"sequence": second},
                f"2026-07-17T10:15:{second:02d}+00:00",
            )

        points = database_service.query_device_snapshots(
            "fts-ls", "all", limit=3
        )
        self.assertEqual(len(points), 3)
        self.assertEqual(points[0]["snapshot"]["sequence"], 0)
        self.assertEqual(points[-1]["snapshot"]["sequence"], 9)

    def test_raw_history_returns_every_sample_without_aggregation(self):
        database_service.write_measurement(
            {"PiA": 1.0, "PoA": 3.0}, "2026-07-17T10:15:30+00:00"
        )
        database_service.write_measurement(
            {"PiA": 3.0, "PoA": 5.0}, "2026-07-17T10:15:30.500000+00:00"
        )

        points = database_service.query_raw_history(
            "5m",
            start="2026-07-17T10:15:00+00:00",
            end="2026-07-17T10:16:00+00:00",
        )

        self.assertEqual(len(points), 2)
        self.assertEqual([point["PiA"] for point in points], [1.0, 3.0])
        self.assertEqual(
            [point["time"] for point in points],
            [
                "2026-07-17T10:15:30+00:00",
                "2026-07-17T10:15:30.500000+00:00",
            ],
        )

    def test_raw_history_stream_does_not_block_writer_connection(self):
        database_service.write_measurement(
            {"PiA": 1.0}, "2026-07-17T10:15:30+00:00"
        )
        database_service.write_measurement(
            {"PiA": 2.0}, "2026-07-17T10:15:31+00:00"
        )
        points = database_service.stream_raw_history(
            "5m",
            start="2026-07-17T10:15:00+00:00",
            end="2026-07-17T10:16:00+00:00",
            batch_size=1,
        )

        first = next(points)
        self.assertEqual(first["PiA"], 1.0)
        self.assertTrue(
            database_service.write_measurement(
                {"PiA": 3.0}, "2026-07-17T10:15:32+00:00"
            )
        )
        self.assertEqual([point["PiA"] for point in points], [2.0])

    def test_setpoint_is_stored_as_separate_measurement(self):
        database_service.write_setpoint(12.5, "2026-07-17T10:15:30+00:00")
        row = database_service.connection.execute(
            "SELECT timestamp_ms, gain_set FROM setpoint_events"
        ).fetchone()
        self.assertEqual(row["timestamp_ms"], 1784283330000)
        self.assertEqual(row["gain_set"], 12.5)

    def test_legacy_json_database_is_migrated_without_data_loss(self):
        database_service.close_database()
        legacy = database_service.sqlite3.connect(config.DATABASE_FILE)
        legacy.execute(
            """
            CREATE TABLE measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                measurement TEXT NOT NULL,
                device TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                timestamp_epoch REAL NOT NULL,
                fields_json TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        legacy.execute(
            """
            INSERT INTO measurements
                (measurement, device, timestamp, timestamp_epoch, fields_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "optical_amp_status",
                config.DEVICE_NAME,
                "2026-07-17T10:15:30+00:00",
                1784283330.0,
                '{"PiA":1.25,"PoA":4.5}',
                1784283330,
            ),
        )
        legacy.commit()
        legacy.close()

        database_service.init_database()

        row = database_service.connection.execute(
            "SELECT timestamp_ms, PiA, PoA FROM samples"
        ).fetchone()
        self.assertEqual(dict(row), {
            "timestamp_ms": 1784283330000,
            "PiA": 1.25,
            "PoA": 4.5,
        })
        old_table = database_service.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='measurements'"
        ).fetchone()
        self.assertIsNone(old_table)

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
