import datetime
import json
import logging
import pathlib
import shutil
import sqlite3
import threading

import config
import state
import syslog_service


logger = logging.getLogger(__name__)
connection = None
database_lock = threading.RLock()
last_error = None
discarded_records = 0

HISTORY_FIELDS = (
    "M",
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
    "seq_nr",
)


def _timestamp_epoch(timestamp: str | None) -> tuple[str, float]:
    if timestamp:
        normalized = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
        parsed = datetime.datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        else:
            parsed = parsed.astimezone(datetime.timezone.utc)
    else:
        parsed = datetime.datetime.now(datetime.timezone.utc)
    return parsed.isoformat(), parsed.timestamp()


def _set_error(operation: str, error: Exception) -> None:
    global last_error
    last_error = f"{operation}: {error}"
    logger.warning("SQLite %s failed: %s", operation, error)


def init_database() -> None:
    global connection
    global last_error

    if connection is not None:
        return
    with database_lock:
        if connection is not None:
            return
        opened_connection = None
        try:
            database_path = pathlib.Path(config.DATABASE_FILE)
            database_path.parent.mkdir(parents=True, exist_ok=True)
            opened_connection = sqlite3.connect(database_path, check_same_thread=False)
            opened_connection.row_factory = sqlite3.Row
            opened_connection.execute("PRAGMA journal_mode=WAL")
            opened_connection.execute("PRAGMA synchronous=NORMAL")
            opened_connection.execute("PRAGMA foreign_keys=ON")
            opened_connection.execute(
                """
                CREATE TABLE IF NOT EXISTS measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    measurement TEXT NOT NULL,
                    device TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    timestamp_epoch REAL NOT NULL,
                    fields_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL DEFAULT (unixepoch())
                )
                """
            )
            opened_connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_measurements_history
                ON measurements (device, measurement, timestamp_epoch)
                """
            )
            opened_connection.commit()
            connection = opened_connection
            last_error = None
        except (OSError, sqlite3.Error) as error:
            _set_error("initialization", error)
            if opened_connection is not None:
                opened_connection.close()


def close_database() -> None:
    global connection
    with database_lock:
        if connection is not None:
            connection.close()
            connection = None


def _numeric_fields(fields: dict) -> dict:
    return {
        key: float(value)
        for key, value in fields.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }


def _prune_to_limit(max_records: int) -> int:
    global discarded_records
    row_count = connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    records_to_remove = max(0, row_count - max_records)
    if records_to_remove:
        connection.execute(
            """
            DELETE FROM measurements
            WHERE id IN (
                SELECT id FROM measurements ORDER BY id ASC LIMIT ?
            )
            """,
            (records_to_remove,),
        )
        discarded_records += records_to_remove
    return records_to_remove


def write_record(measurement: str, fields: dict, timestamp: str | None = None) -> bool:
    global last_error
    values = _numeric_fields(fields)
    if not values:
        return False
    try:
        timestamp_text, timestamp_epoch = _timestamp_epoch(timestamp)
    except (TypeError, ValueError) as error:
        _set_error("timestamp parsing", error)
        return False

    init_database()
    if connection is None:
        return False

    max_records = max(1, int(state.service_settings["database_max_records"]))
    with database_lock:
        try:
            connection.execute(
                """
                INSERT INTO measurements
                    (measurement, device, timestamp, timestamp_epoch, fields_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    measurement,
                    config.DEVICE_NAME,
                    timestamp_text,
                    timestamp_epoch,
                    json.dumps(values, separators=(",", ":"), sort_keys=True),
                ),
            )
            removed = _prune_to_limit(max_records)
            connection.commit()
            last_error = None
        except (OSError, sqlite3.Error) as error:
            connection.rollback()
            _set_error("write", error)
            return False

    if removed:
        syslog_service.send_warning(
            "database_record_limit_reached; "
            f"discarded_oldest_records={removed}; limit={max_records}"
        )
    return True


def write_measurement(data: dict, timestamp: str | None = None) -> bool:
    return write_record(config.MEASUREMENT_NAME, data, timestamp)


def write_setpoint(gain_set: float, timestamp: str | None = None) -> bool:
    return write_record(
        config.SETPOINT_MEASUREMENT_NAME,
        {"gain_set": gain_set},
        timestamp,
    )


def get_record_count() -> int:
    init_database()
    if connection is None:
        return 0
    with database_lock:
        try:
            return connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
        except sqlite3.Error as error:
            _set_error("status", error)
            return 0


def apply_record_limit() -> int:
    init_database()
    if connection is None:
        return 0
    with database_lock:
        try:
            removed = _prune_to_limit(
                max(1, int(state.service_settings["database_max_records"]))
            )
            connection.commit()
            return removed
        except sqlite3.Error as error:
            connection.rollback()
            _set_error("record limit update", error)
            return 0


def get_storage_status() -> dict:
    database_path = pathlib.Path(config.DATABASE_FILE)
    database_files = (
        database_path,
        pathlib.Path(f"{database_path}-wal"),
        pathlib.Path(f"{database_path}-shm"),
    )
    try:
        size_bytes = sum(path.stat().st_size for path in database_files if path.exists())
        free_bytes = shutil.disk_usage(database_path.parent).free
    except OSError as error:
        _set_error("disk status", error)
        size_bytes = 0
        free_bytes = 0
    return {
        "size_bytes": size_bytes,
        "free_bytes": free_bytes,
        "discarded_records_since_start": discarded_records,
    }


def get_runtime_status() -> dict:
    init_database()
    return {
        "state": "ready" if connection is not None else "error",
        "ready": connection is not None,
        "records": get_record_count() if connection is not None else 0,
        "error": last_error,
    }


def _range_start(range_value: str) -> datetime.datetime | None:
    now = datetime.datetime.now(datetime.timezone.utc)
    durations = {
        "5m": datetime.timedelta(minutes=5),
        "1h": datetime.timedelta(hours=1),
        "24h": datetime.timedelta(hours=24),
        "7d": datetime.timedelta(days=7),
        "30d": datetime.timedelta(days=30),
    }
    duration = durations.get(range_value)
    return now - duration if duration else None


def _window_seconds(range_value: str) -> int:
    return {
        "5m": 1,
        "1h": 10,
        "24h": 60,
        "7d": 600,
        "30d": 1800,
        "all": 3600,
    }.get(range_value, 1)


def _parse_boundary(value: str | None) -> float | None:
    if not value:
        return None
    return _timestamp_epoch(value)[1]


def query_history(range_value: str, start: str | None = None, end: str | None = None):
    init_database()
    if connection is None:
        return None

    try:
        start_epoch = _parse_boundary(start)
        if start_epoch is None:
            range_start = _range_start(range_value)
            start_epoch = range_start.timestamp() if range_start else None
        end_epoch = _parse_boundary(end)

        clauses = ["device = ?", "measurement = ?"]
        parameters = [config.DEVICE_NAME, config.MEASUREMENT_NAME]
        if start_epoch is not None:
            clauses.append("timestamp_epoch >= ?")
            parameters.append(start_epoch)
        if end_epoch is not None:
            clauses.append("timestamp_epoch <= ?")
            parameters.append(end_epoch)

        sql = (
            "SELECT timestamp, timestamp_epoch, fields_json FROM measurements WHERE "
            + " AND ".join(clauses)
            + " ORDER BY timestamp_epoch ASC"
        )
    except (TypeError, ValueError, sqlite3.Error) as error:
        _set_error("history query", error)
        return None

    window = _window_seconds(range_value)
    buckets = {}
    try:
        with database_lock:
            rows = connection.execute(sql, parameters)
            for row in rows:
                bucket_epoch = int(float(row["timestamp_epoch"]) // window) * window
                bucket = buckets.setdefault(bucket_epoch, {})
                try:
                    fields = json.loads(row["fields_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                for field in HISTORY_FIELDS:
                    value = fields.get(field)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        total, count = bucket.get(field, (0.0, 0))
                        bucket[field] = (total + float(value), count + 1)
    except sqlite3.Error as error:
        _set_error("history query", error)
        return None

    points = []
    for bucket_epoch, fields in sorted(buckets.items()):
        point = {
            "time": datetime.datetime.fromtimestamp(
                bucket_epoch, datetime.timezone.utc
            ).isoformat()
        }
        for field, (total, count) in fields.items():
            point[field] = total / count
        points.append(point)
    return points
