import datetime
import json
import logging
import pathlib
import shutil
import sqlite3
import threading

from app.core import config, state
from app.services import syslog as syslog_service


logger = logging.getLogger(__name__)
connection = None
database_lock = threading.RLock()
last_error = None
discarded_records = 0
LEGACY_SETPOINT_MEASUREMENT = "optical_amp_setpoint"

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
FIELD_COLUMNS = ", ".join(HISTORY_FIELDS)
FIELD_PLACEHOLDERS = ", ".join("?" for _ in HISTORY_FIELDS)


def _timestamp_ms(timestamp: str | None) -> int:
    if timestamp:
        normalized = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
        parsed = datetime.datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        else:
            parsed = parsed.astimezone(datetime.timezone.utc)
    else:
        parsed = datetime.datetime.now(datetime.timezone.utc)
    return round(parsed.timestamp() * 1000)


def _set_error(operation: str, error: Exception) -> None:
    global last_error
    last_error = f"{operation}: {error}"
    logger.warning("SQLite %s failed: %s", operation, error)


def _create_schema(opened_connection: sqlite3.Connection) -> None:
    opened_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS samples (
            id INTEGER PRIMARY KEY,
            timestamp_ms INTEGER NOT NULL,
            M REAL,
            PiA REAL,
            PoA REAL,
            PiB REAL,
            PoB REAL,
            G REAL,
            SG REAL,
            PP REAL,
            SPP REAL,
            gain_set REAL,
            gain_actual REAL,
            gain_delta REAL,
            temperature REAL,
            seq_nr REAL
        )
        """
    )
    opened_connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_samples_timestamp ON samples (timestamp_ms)"
    )
    opened_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS setpoint_events (
            id INTEGER PRIMARY KEY,
            timestamp_ms INTEGER NOT NULL,
            gain_set REAL NOT NULL
        )
        """
    )
    opened_connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_setpoints_timestamp ON setpoint_events (timestamp_ms)"
    )
    opened_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS database_metadata (
            key TEXT PRIMARY KEY,
            value INTEGER NOT NULL
        ) WITHOUT ROWID
        """
    )
    opened_connection.execute(
        """
        INSERT OR IGNORE INTO database_metadata (key, value)
        VALUES ('sample_count', (SELECT COUNT(*) FROM samples))
        """
    )
    opened_connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS samples_count_after_insert
        AFTER INSERT ON samples
        BEGIN
            UPDATE database_metadata SET value = value + 1
            WHERE key = 'sample_count';
        END
        """
    )
    opened_connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS samples_count_after_delete
        AFTER DELETE ON samples
        BEGIN
            UPDATE database_metadata SET value = value - 1
            WHERE key = 'sample_count';
        END
        """
    )


def _legacy_measurements_exist(opened_connection: sqlite3.Connection) -> bool:
    table = opened_connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='measurements'"
    ).fetchone()
    if not table:
        return False
    columns = {
        row["name"] for row in opened_connection.execute("PRAGMA table_info(measurements)")
    }
    return "fields_json" in columns and "timestamp_epoch" in columns


def _migrate_legacy_measurements(opened_connection: sqlite3.Connection) -> None:
    if not _legacy_measurements_exist(opened_connection):
        return

    rows = opened_connection.execute(
        "SELECT measurement, timestamp_epoch, fields_json FROM measurements ORDER BY id"
    )
    sample_sql = (
        f"INSERT INTO samples (timestamp_ms, {FIELD_COLUMNS}) "
        f"VALUES (?, {FIELD_PLACEHOLDERS})"
    )
    for row in rows:
        try:
            fields = json.loads(row["fields_json"])
            timestamp_ms = round(float(row["timestamp_epoch"]) * 1000)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if row["measurement"] == LEGACY_SETPOINT_MEASUREMENT:
            gain_set = fields.get("gain_set")
            if isinstance(gain_set, (int, float)) and not isinstance(gain_set, bool):
                opened_connection.execute(
                    "INSERT INTO setpoint_events (timestamp_ms, gain_set) VALUES (?, ?)",
                    (timestamp_ms, float(gain_set)),
                )
            continue
        values = [
            float(fields[field])
            if isinstance(fields.get(field), (int, float))
            and not isinstance(fields.get(field), bool)
            else None
            for field in HISTORY_FIELDS
        ]
        opened_connection.execute(sample_sql, (timestamp_ms, *values))

    opened_connection.execute("DROP TABLE measurements")


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
            with opened_connection:
                _create_schema(opened_connection)
                _migrate_legacy_measurements(opened_connection)
                opened_connection.execute("PRAGMA user_version=2")
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
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.close()
            connection = None


def _field_values(fields: dict) -> list[float | None]:
    return [
        float(fields[field])
        if isinstance(fields.get(field), (int, float))
        and not isinstance(fields.get(field), bool)
        else None
        for field in HISTORY_FIELDS
    ]


def _prune_to_limit(max_records: int) -> int:
    global discarded_records
    row_count = connection.execute(
        "SELECT value FROM database_metadata WHERE key = 'sample_count'"
    ).fetchone()[0]
    records_to_remove = max(0, row_count - max_records)
    if records_to_remove:
        connection.execute(
            """
            DELETE FROM samples
            WHERE id IN (SELECT id FROM samples ORDER BY id ASC LIMIT ?)
            """,
            (records_to_remove,),
        )
        discarded_records += records_to_remove
    return records_to_remove


def write_measurement(data: dict, timestamp: str | None = None) -> bool:
    global last_error
    values = _field_values(data)
    if not any(value is not None for value in values):
        return False
    try:
        timestamp_value = _timestamp_ms(timestamp)
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
                f"INSERT INTO samples (timestamp_ms, {FIELD_COLUMNS}) "
                f"VALUES (?, {FIELD_PLACEHOLDERS})",
                (timestamp_value, *values),
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


def write_setpoint(gain_set: float, timestamp: str | None = None) -> bool:
    global last_error
    try:
        timestamp_value = _timestamp_ms(timestamp)
        gain_value = float(gain_set)
    except (TypeError, ValueError) as error:
        _set_error("setpoint parsing", error)
        return False
    init_database()
    if connection is None:
        return False
    with database_lock:
        try:
            connection.execute(
                "INSERT INTO setpoint_events (timestamp_ms, gain_set) VALUES (?, ?)",
                (timestamp_value, gain_value),
            )
            connection.commit()
            last_error = None
            return True
        except (OSError, sqlite3.Error) as error:
            connection.rollback()
            _set_error("setpoint write", error)
            return False


def get_record_count() -> int:
    init_database()
    if connection is None:
        return 0
    with database_lock:
        try:
            return connection.execute(
                "SELECT value FROM database_metadata WHERE key = 'sample_count'"
            ).fetchone()[0]
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


def _parse_boundary(value: str | None) -> int | None:
    return _timestamp_ms(value) if value else None


def query_history(range_value: str, start: str | None = None, end: str | None = None):
    init_database()
    if connection is None:
        return None

    try:
        start_ms = _parse_boundary(start)
        if start_ms is None:
            range_start = _range_start(range_value)
            start_ms = round(range_start.timestamp() * 1000) if range_start else None
        end_ms = _parse_boundary(end)
        window_ms = _window_seconds(range_value) * 1000

        clauses = []
        parameters = []
        if start_ms is not None:
            clauses.append("timestamp_ms >= ?")
            parameters.append(start_ms)
        if end_ms is not None:
            clauses.append("timestamp_ms <= ?")
            parameters.append(end_ms)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        averages = ", ".join(f"AVG({field}) AS {field}" for field in HISTORY_FIELDS)
        sql = f"""
            SELECT (timestamp_ms / ?) * ? AS bucket_ms, {averages}
            FROM samples
            {where_clause}
            GROUP BY bucket_ms
            ORDER BY bucket_ms ASC
        """
        with database_lock:
            rows = connection.execute(sql, (window_ms, window_ms, *parameters)).fetchall()
    except (TypeError, ValueError, sqlite3.Error) as error:
        _set_error("history query", error)
        return None

    points = []
    for row in rows:
        point = {
            "time": datetime.datetime.fromtimestamp(
                row["bucket_ms"] / 1000, datetime.timezone.utc
            ).isoformat()
        }
        for field in HISTORY_FIELDS:
            if row[field] is not None:
                point[field] = row[field]
        points.append(point)
    return points


def query_raw_history(range_value: str, start: str | None = None, end: str | None = None):
    """Return every stored sample in the selected period without aggregation."""
    init_database()
    if connection is None:
        return None

    try:
        start_ms = _parse_boundary(start)
        if start_ms is None:
            range_start = _range_start(range_value)
            start_ms = round(range_start.timestamp() * 1000) if range_start else None
        end_ms = _parse_boundary(end)

        clauses = []
        parameters = []
        if start_ms is not None:
            clauses.append("timestamp_ms >= ?")
            parameters.append(start_ms)
        if end_ms is not None:
            clauses.append("timestamp_ms <= ?")
            parameters.append(end_ms)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT timestamp_ms, {FIELD_COLUMNS}
            FROM samples
            {where_clause}
            ORDER BY timestamp_ms ASC, id ASC
        """
        with database_lock:
            rows = connection.execute(sql, parameters).fetchall()
    except (TypeError, ValueError, sqlite3.Error) as error:
        _set_error("raw history query", error)
        return None

    points = []
    for row in rows:
        point = {
            "time": datetime.datetime.fromtimestamp(
                row["timestamp_ms"] / 1000, datetime.timezone.utc
            ).isoformat()
        }
        for field in HISTORY_FIELDS:
            if row[field] is not None:
                point[field] = row[field]
        points.append(point)
    return points
