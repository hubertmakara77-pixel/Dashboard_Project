import json
import logging
import pathlib
import shutil
import sqlite3
import threading
import time

import config
import state
import syslog_service


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
buffer_connection = None
buffer_lock = threading.Lock()
buffer_worker = None
buffer_stop_event = threading.Event()
buffer_wakeup_event = threading.Event()
buffer_discarded_records = 0


def _log_failure(operation: str, error: Exception) -> bool:
    now = time.monotonic()
    if now - last_error_log.get(operation, 0) >= 60:
        logger.warning("InfluxDB %s failed: %s", operation, error)
        last_error_log[operation] = now
        return True
    return False


def init_influx_buffer() -> None:
    global buffer_connection

    if buffer_connection is not None:
        return

    with buffer_lock:
        if buffer_connection is not None:
            return
        connection = None
        try:
            buffer_path = pathlib.Path(config.INFLUX_BUFFER_FILE)
            buffer_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(buffer_path, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            # NORMAL keeps WAL transactions consistent while avoiding an
            # expensive storage flush for every sample on embedded flash.
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_influx_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    measurement TEXT NOT NULL,
                    device TEXT NOT NULL,
                    fields_json TEXT NOT NULL,
                    timestamp TEXT,
                    created_at INTEGER NOT NULL DEFAULT (unixepoch())
                )
                """
            )
            connection.commit()
            buffer_connection = connection
        except (OSError, sqlite3.Error) as error:
            _log_failure("local buffer initialization", error)
            if connection is not None:
                connection.close()


def _enqueue_record(measurement: str, fields: dict, timestamp: str | None) -> None:
    global buffer_discarded_records
    numeric_fields = {
        key: float(value)
        for key, value in fields.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    if not numeric_fields:
        return

    init_influx_buffer()
    if buffer_connection is None:
        return

    max_records = max(1, int(state.service_settings["influx_buffer_max_records"]))
    with buffer_lock:
        try:
            row_count = buffer_connection.execute(
                "SELECT COUNT(*) FROM pending_influx_records"
            ).fetchone()[0]
            if row_count >= max_records:
                records_to_remove = row_count - max_records + 1
                buffer_discarded_records += records_to_remove
                buffer_connection.execute(
                    """
                    DELETE FROM pending_influx_records
                    WHERE id IN (
                        SELECT id FROM pending_influx_records
                        ORDER BY id ASC
                        LIMIT ?
                    )
                    """,
                    (records_to_remove,),
                )
                if _log_failure(
                    "local buffer capacity",
                    RuntimeError(f"discarded {records_to_remove} oldest record(s)"),
                ):
                    syslog_service.send_warning(
                        "influx_buffer_record_limit_reached; "
                        f"discarded_oldest_records={records_to_remove}; limit={max_records}"
                    )

            buffer_connection.execute(
                """
                INSERT INTO pending_influx_records
                    (measurement, device, fields_json, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (
                    measurement,
                    config.DEVICE_NAME,
                    json.dumps(numeric_fields, separators=(",", ":"), sort_keys=True),
                    timestamp,
                ),
            )
            buffer_connection.commit()
        except (OSError, sqlite3.Error) as error:
            buffer_connection.rollback()
            _log_failure("local buffer write", error)
            return
    buffer_wakeup_event.set()


def get_pending_record_count() -> int:
    init_influx_buffer()
    if buffer_connection is None:
        return 0
    with buffer_lock:
        try:
            return buffer_connection.execute(
                "SELECT COUNT(*) FROM pending_influx_records"
            ).fetchone()[0]
        except sqlite3.Error as error:
            _log_failure("local buffer status", error)
            return 0


def apply_buffer_limits() -> int:
    init_influx_buffer()
    if buffer_connection is None:
        return 0
    max_records = max(1, int(state.service_settings["influx_buffer_max_records"]))
    with buffer_lock:
        try:
            row_count = buffer_connection.execute(
                "SELECT COUNT(*) FROM pending_influx_records"
            ).fetchone()[0]
            records_to_remove = max(0, row_count - max_records)
            if records_to_remove:
                buffer_connection.execute(
                    """
                    DELETE FROM pending_influx_records
                    WHERE id IN (
                        SELECT id FROM pending_influx_records
                        ORDER BY id ASC
                        LIMIT ?
                    )
                    """,
                    (records_to_remove,),
                )
                buffer_connection.commit()
            return records_to_remove
        except sqlite3.Error as error:
            buffer_connection.rollback()
            _log_failure("local buffer limit update", error)
            return 0


def get_buffer_storage_status() -> dict:
    buffer_path = pathlib.Path(config.INFLUX_BUFFER_FILE)
    buffer_files = (buffer_path, pathlib.Path(f"{buffer_path}-wal"), pathlib.Path(f"{buffer_path}-shm"))
    try:
        size_bytes = sum(path.stat().st_size for path in buffer_files if path.exists())
        free_bytes = shutil.disk_usage(buffer_path.parent).free
    except OSError as error:
        _log_failure("local buffer disk status", error)
        size_bytes = 0
        free_bytes = 0
    return {
        "size_bytes": size_bytes,
        "free_bytes": free_bytes,
        "discarded_records_since_start": buffer_discarded_records,
    }


def get_runtime_status() -> dict:
    pending_records = get_pending_record_count()
    connected = client is not None and write_api is not None and query_api is not None
    if connected and pending_records:
        runtime_state = "syncing"
    elif connected:
        runtime_state = "connected"
    elif pending_records:
        runtime_state = "buffering"
    else:
        runtime_state = "disconnected"
    return {
        "state": runtime_state,
        "connected": connected,
        "pending_records": pending_records,
    }


def _write_buffered_record(record: sqlite3.Row) -> None:
    point = influxdb_client.Point(record["measurement"])
    point = point.tag("device", record["device"])
    for key, value in json.loads(record["fields_json"]).items():
        point = point.field(key, float(value))
    if record["timestamp"] is not None:
        point = point.time(record["timestamp"])
    write_api.write(
        bucket=config.INFLUX_BUCKET,
        org=config.INFLUX_ORG,
        record=point,
    )


def flush_influx_buffer() -> int:
    if not _ensure_connected():
        return 0

    init_influx_buffer()
    if buffer_connection is None:
        return 0

    batch_size = max(1, config.INFLUX_BUFFER_BATCH_SIZE)
    with buffer_lock:
        try:
            records = buffer_connection.execute(
                "SELECT * FROM pending_influx_records ORDER BY id ASC LIMIT ?",
                (batch_size,),
            ).fetchall()
        except sqlite3.Error as error:
            _log_failure("local buffer read", error)
            return 0

    sent_ids = []
    for record in records:
        try:
            _write_buffered_record(record)
            sent_ids.append(record["id"])
        except Exception as error:
            _log_failure("buffer flush", error)
            _disconnect_for_retry()
            break

    if sent_ids:
        placeholders = ",".join("?" for _ in sent_ids)
        with buffer_lock:
            try:
                buffer_connection.execute(
                    f"DELETE FROM pending_influx_records WHERE id IN ({placeholders})",
                    sent_ids,
                )
                buffer_connection.commit()
            except sqlite3.Error as error:
                buffer_connection.rollback()
                _log_failure("local buffer cleanup", error)
    return len(sent_ids)


def _buffer_worker_loop() -> None:
    while not buffer_stop_event.is_set():
        sent_count = flush_influx_buffer()
        if sent_count >= max(1, config.INFLUX_BUFFER_BATCH_SIZE):
            continue
        buffer_wakeup_event.wait(max(1, config.INFLUX_RETRY_SECONDS))
        buffer_wakeup_event.clear()


def start_influx_buffer_worker() -> None:
    global buffer_worker
    init_influx_buffer()
    if buffer_worker is not None and buffer_worker.is_alive():
        return
    buffer_stop_event.clear()
    buffer_worker = threading.Thread(
        target=_buffer_worker_loop,
        name="influx-buffer-worker",
        daemon=True,
    )
    buffer_worker.start()


def stop_influx_buffer_worker() -> None:
    global buffer_connection
    global buffer_worker
    buffer_stop_event.set()
    buffer_wakeup_event.set()
    if buffer_worker is not None:
        buffer_worker.join(timeout=5)
        if buffer_worker.is_alive():
            _log_failure("buffer shutdown", TimeoutError("worker did not stop within 5 seconds"))
            return
    with buffer_lock:
        if buffer_connection is not None:
            buffer_connection.close()
            buffer_connection = None
    buffer_worker = None


def init_influx():
    global client
    global write_api
    global query_api
    global next_reconnect_at

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
        next_reconnect_at = time.monotonic() + max(1, config.INFLUX_RETRY_SECONDS)


def _ensure_connected() -> bool:
    global next_reconnect_at
    if influxdb_client is None:
        return False
    if client is not None and write_api is not None and query_api is not None:
        return True
    with connection_lock:
        if client is not None and write_api is not None and query_api is not None:
            return True
        if time.monotonic() < next_reconnect_at:
            return False
        next_reconnect_at = time.monotonic() + max(1, config.INFLUX_RETRY_SECONDS)
        init_influx()
        return client is not None and write_api is not None and query_api is not None


def _disconnect_for_retry() -> None:
    global next_reconnect_at
    with connection_lock:
        close_influx()
    next_reconnect_at = time.monotonic() + max(1, config.INFLUX_RETRY_SECONDS)


def write_measurement(data: dict, timestamp: str | None = None):
    _enqueue_record(config.MEASUREMENT_NAME, data, timestamp)


def write_setpoint(gain_set: float, timestamp: str | None = None):
    _enqueue_record(
        config.SETPOINT_MEASUREMENT_NAME,
        {"gain_set": gain_set},
        timestamp,
    )


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
