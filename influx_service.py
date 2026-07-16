import logging
import threading
import time

import config


try:
    import influxdb_client
    import influxdb_client.client.write_api
except ImportError:
    influxdb_client = None


client = None
write_api = None
query_api = None
logger = logging.getLogger(__name__)
last_error_log = {}
next_reconnect_at = 0.0
connection_lock = threading.Lock()


def _log_failure(operation: str, error: Exception) -> None:
    now = time.monotonic()
    if now - last_error_log.get(operation, 0) >= 60:
        logger.warning("InfluxDB %s failed: %s", operation, error)
        last_error_log[operation] = now


def init_influx():
    global client
    global write_api
    global query_api
    global next_reconnect_at

    if not config.INFLUX_ENABLED:
        print("InfluxDB disabled in config.py")
        return

    if influxdb_client is None:
        print("Missing influxdb-client library")
        print("Install it with: py -3.14 -m pip install influxdb-client")
        return

    if not config.INFLUX_TOKEN:
        _log_failure("configuration", ValueError("INFLUX_TOKEN is not configured"))
        return

    try:
        client = influxdb_client.InfluxDBClient(
            url=config.INFLUX_URL,
            token=config.INFLUX_TOKEN,
            org=config.INFLUX_ORG
        )
        if not client.ping():
            raise ConnectionError("health check failed")
        write_api = client.write_api(
            write_options=influxdb_client.client.write_api.SYNCHRONOUS
        )
        query_api = client.query_api()
        print("Connected to InfluxDB")
    except Exception as error:
        _log_failure("initialization", error)
        close_influx()
        next_reconnect_at = time.monotonic() + 10


def _ensure_connected() -> bool:
    global next_reconnect_at
    if not config.INFLUX_ENABLED or influxdb_client is None:
        return False
    if client is not None and write_api is not None and query_api is not None:
        return True
    with connection_lock:
        if client is not None and write_api is not None and query_api is not None:
            return True
        if time.monotonic() < next_reconnect_at:
            return False
        next_reconnect_at = time.monotonic() + 10
        init_influx()
        return client is not None and write_api is not None and query_api is not None


def _disconnect_for_retry() -> None:
    global next_reconnect_at
    with connection_lock:
        close_influx()
        next_reconnect_at = time.monotonic() + 10


def write_measurement(data: dict, timestamp: str | None = None):
    if not config.INFLUX_ENABLED:
        return

    if not _ensure_connected():
        return

    point = influxdb_client.Point(config.MEASUREMENT_NAME)
    point = point.tag("device", config.DEVICE_NAME)

    for key, value in data.items():
        if isinstance(value, int) or isinstance(value, float):
            point = point.field(key, float(value))

    if timestamp is not None:
        point = point.time(timestamp)

    try:
        write_api.write(
            bucket=config.INFLUX_BUCKET,
            org=config.INFLUX_ORG,
            record=point
        )
    except Exception as error:
        _log_failure("measurement write", error)
        _disconnect_for_retry()


def write_setpoint(gain_set: float, timestamp: str | None = None):
    if not config.INFLUX_ENABLED:
        return

    if not _ensure_connected():
        return

    point = influxdb_client.Point(config.SETPOINT_MEASUREMENT_NAME)
    point = point.tag("device", config.DEVICE_NAME)
    point = point.field("gain_set", float(gain_set))
    if timestamp is not None:
        point = point.time(timestamp)

    try:
        write_api.write(
            bucket=config.INFLUX_BUCKET,
            org=config.INFLUX_ORG,
            record=point
        )
    except Exception as error:
        _log_failure("setpoint write", error)
        _disconnect_for_retry()


def get_window_for_range(range_value: str) -> str:
    if range_value == "5m":
        return "1s"

    if range_value == "1h":
        return "10s"

    if range_value == "24h":
        return "1m"

    if range_value == "7d":
        return "10m"

    if range_value == "30d":
        return "30m"

    if range_value == "all":
        return "1h"

    return "1s"


def get_flux_range(range_value: str) -> str:
    if range_value == "5m":
        return "-5m"

    if range_value == "1h":
        return "-1h"

    if range_value == "24h":
        return "-24h"

    if range_value == "7d":
        return "-7d"

    if range_value == "30d":
        return "-30d"

    if range_value == "all":
        return "0"

    return "-5m"


def get_flux_range_clause(range_value: str, start: str | None = None, end: str | None = None) -> str:
    if start:
        stop_clause = f', stop: time(v: "{end}")' if end else ""
        return f'|> range(start: time(v: "{start}"){stop_clause})'

    return f"|> range(start: {get_flux_range(range_value)})"


def query_history_from_influx(range_value: str, start: str | None = None, end: str | None = None):
    if not config.INFLUX_ENABLED:
        return None

    if not _ensure_connected():
        return None

    flux_range_clause = get_flux_range_clause(range_value, start, end)
    window = get_window_for_range(range_value)

    fields = [
        "PiA",
        "PoA",
        "PiB",
        "PoB",
        "G",
        "SG",
        "PP",
        "SPP",
        "gain_set",
        "gain_actual",
        "gain_delta",
        "temperature",
    ]

    field_filter = " or ".join([
        f'r._field == "{field}"'
        for field in fields
    ])

    query = f'''
from(bucket: "{config.INFLUX_BUCKET}")
  {flux_range_clause}
  |> filter(fn: (r) => r._measurement == "{config.MEASUREMENT_NAME}")
  |> filter(fn: (r) => r.device == "{config.DEVICE_NAME}")
  |> filter(fn: (r) => {field_filter})
  |> aggregateWindow(every: {window}, fn: mean, createEmpty: false)
  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
'''

    try:
        tables = query_api.query(query, org=config.INFLUX_ORG)
    except Exception as error:
        _log_failure("history query", error)
        _disconnect_for_retry()
        return None

    points = []

    for table in tables:
        for record in table.records:
            point = {
                "time": record.values["_time"].isoformat()
            }

            for field in fields:
                if field in record.values:
                    point[field] = record.values[field]

            points.append(point)

    points.sort(key=lambda item: item["time"])

    return points


def close_influx():
    global client
    global write_api
    global query_api

    if client is not None:
        try:
            client.close()
        except Exception as error:
            _log_failure("shutdown", error)

    client = None
    write_api = None
    query_api = None
