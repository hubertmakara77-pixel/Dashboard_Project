import unittest
from unittest import mock

import config
import influx_service


class FakePoint:
    timestamps = []

    def __init__(self, *_args):
        pass

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


class FakeClient:
    def close(self):
        pass


class InfluxResilienceTests(unittest.TestCase):
    def setUp(self):
        FakePoint.timestamps.clear()
        self.originals = (
            influx_service.influxdb_client,
            influx_service.client,
            influx_service.write_api,
            influx_service.query_api,
        )
        influx_service.influxdb_client = FakeInfluxModule()
        influx_service.client = FakeClient()
        influx_service.write_api = FailingApi()
        influx_service.query_api = FailingApi()

    def tearDown(self):
        (
            influx_service.influxdb_client,
            influx_service.client,
            influx_service.write_api,
            influx_service.query_api,
        ) = self.originals

    def test_measurement_failure_does_not_escape(self):
        with mock.patch.object(config, "INFLUX_ENABLED", True):
            influx_service.write_measurement({"PiA": 1.0})
        self.assertIsNone(influx_service.client)

    def test_measurement_uses_explicit_sample_timestamp(self):
        timestamp = "2026-07-17T10:15:30+00:00"
        with mock.patch.object(config, "INFLUX_ENABLED", True):
            influx_service.write_measurement({"PiA": 1.0}, timestamp)
        self.assertEqual(FakePoint.timestamps, [timestamp])

    def test_query_failure_falls_back_to_memory(self):
        with mock.patch.object(config, "INFLUX_ENABLED", True):
            result = influx_service.query_history_from_influx("5m")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
