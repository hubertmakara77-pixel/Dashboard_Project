import datetime
import json
import logging
import math
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
HOUR_MS = 60 * 60 * 1000


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
    opened_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS hourly_statistics (
            bucket_ms INTEGER PRIMARY KEY,
            sample_count INTEGER NOT NULL,
            statistics_json TEXT NOT NULL
        )
        """
    )


def _empty_statistics_state() -> dict:
    return {
        field: {
            "count": 0,
            "sum": 0.0,
            "sum_squares": 0.0,
            "min": None,
            "max": None,
        }
        for field in HISTORY_FIELDS
    }


def _consume_statistics_row(
    statistics: dict,
    row: sqlite3.Row,
) -> None:
    for field in HISTORY_FIELDS:
        value = row[field]
        field_state = statistics[field]
        if value is not None:
            numeric_value = float(value)
            field_state["count"] += 1
            field_state["sum"] += numeric_value
            field_state["sum_squares"] += numeric_value * numeric_value
            field_state["min"] = (
                numeric_value
                if field_state["min"] is None
                else min(field_state["min"], numeric_value)
            )
            field_state["max"] = (
                numeric_value
                if field_state["max"] is None
                else max(field_state["max"], numeric_value)
            )


def _store_hourly_statistics(
    opened_connection: sqlite3.Connection,
    bucket_ms: int,
    sample_count: int,
    statistics: dict,
) -> None:
    opened_connection.execute(
        """
        INSERT INTO hourly_statistics (bucket_ms, sample_count, statistics_json)
        VALUES (?, ?, ?)
        ON CONFLICT(bucket_ms) DO UPDATE SET
            sample_count = excluded.sample_count,
            statistics_json = excluded.statistics_json
        """,
        (bucket_ms, sample_count, json.dumps(statistics, separators=(",", ":"))),
    )


def _rebuild_hourly_bucket(
    opened_connection: sqlite3.Connection,
    bucket_ms: int,
) -> None:
    rows = opened_connection.execute(
        f"""
        SELECT {FIELD_COLUMNS}
        FROM samples
        WHERE timestamp_ms >= ? AND timestamp_ms < ?
        ORDER BY timestamp_ms ASC, id ASC
        """,
        (bucket_ms, bucket_ms + HOUR_MS),
    )
    statistics = _empty_statistics_state()
    sample_count = 0
    for row in rows:
        _consume_statistics_row(statistics, row)
        sample_count += 1
    if sample_count:
        _store_hourly_statistics(
            opened_connection, bucket_ms, sample_count, statistics
        )
    else:
        opened_connection.execute(
            "DELETE FROM hourly_statistics WHERE bucket_ms = ?", (bucket_ms,)
        )


def _backfill_hourly_statistics(opened_connection: sqlite3.Connection) -> None:
    """Build persistent summaries once for completed historical hours."""
    bounds = opened_connection.execute(
        "SELECT MIN(timestamp_ms), MAX(timestamp_ms) FROM samples"
    ).fetchone()
    if bounds[0] is None:
        return
    last_bucket_ms = (int(bounds[1]) // HOUR_MS) * HOUR_MS
    summarized_buckets = {
        row[0]
        for row in opened_connection.execute(
            "SELECT bucket_ms FROM hourly_statistics"
        )
    }
    rows = opened_connection.execute(
        f"""
        SELECT timestamp_ms, {FIELD_COLUMNS}
        FROM samples
        WHERE timestamp_ms < ?
        ORDER BY timestamp_ms ASC, id ASC
        """,
        (last_bucket_ms,),
    )
    current_bucket = None
    current_count = 0
    statistics = None
    for row in rows:
        bucket_ms = (int(row["timestamp_ms"]) // HOUR_MS) * HOUR_MS
        if bucket_ms != current_bucket:
            if current_bucket is not None and current_bucket not in summarized_buckets:
                _store_hourly_statistics(
                    opened_connection, current_bucket, current_count, statistics
                )
            current_bucket = bucket_ms
            current_count = 0
            statistics = _empty_statistics_state()
        if bucket_ms not in summarized_buckets:
            _consume_statistics_row(statistics, row)
            current_count += 1
    if current_bucket is not None and current_bucket not in summarized_buckets:
        _store_hourly_statistics(
            opened_connection, current_bucket, current_count, statistics
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
                schema_version = opened_connection.execute(
                    "PRAGMA user_version"
                ).fetchone()[0]
                _create_schema(opened_connection)
                _migrate_legacy_measurements(opened_connection)
                if schema_version < 4:
                    opened_connection.execute("DELETE FROM hourly_statistics")
                    _backfill_hourly_statistics(opened_connection)
                opened_connection.execute("PRAGMA user_version=4")
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
        remaining_bounds = connection.execute(
            "SELECT MIN(timestamp_ms), MAX(timestamp_ms) FROM samples"
        ).fetchone()
        if remaining_bounds[0] is None:
            connection.execute("DELETE FROM hourly_statistics")
        else:
            first_bucket_ms = (int(remaining_bounds[0]) // HOUR_MS) * HOUR_MS
            connection.execute(
                "DELETE FROM hourly_statistics WHERE bucket_ms <= ?",
                (first_bucket_ms,),
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
            previous_last_timestamp = connection.execute(
                "SELECT MAX(timestamp_ms) FROM samples"
            ).fetchone()[0]
            connection.execute(
                f"INSERT INTO samples (timestamp_ms, {FIELD_COLUMNS}) "
                f"VALUES (?, {FIELD_PLACEHOLDERS})",
                (timestamp_value, *values),
            )
            inserted_bucket_ms = (timestamp_value // HOUR_MS) * HOUR_MS
            if previous_last_timestamp is not None:
                previous_bucket_ms = (
                    int(previous_last_timestamp) // HOUR_MS
                ) * HOUR_MS
                if inserted_bucket_ms > previous_bucket_ms:
                    _rebuild_hourly_bucket(connection, previous_bucket_ms)
                elif inserted_bucket_ms < previous_bucket_ms:
                    # Historical/out-of-order inserts may target a bucket that
                    # is already summarized.
                    summarized = connection.execute(
                        "SELECT 1 FROM hourly_statistics WHERE bucket_ms = ?",
                        (inserted_bucket_ms,),
                    ).fetchone()
                    if summarized:
                        _rebuild_hourly_bucket(connection, inserted_bucket_ms)
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


def query_history(
    range_value: str,
    start: str | None = None,
    end: str | None = None,
    include_metadata: bool = False,
):
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
        with database_lock:
            bounds = connection.execute(
                f"SELECT MIN(timestamp_ms) AS first_ms, MAX(timestamp_ms) AS last_ms "
                f"FROM samples {where_clause}",
                parameters,
            ).fetchone()
        if bounds["first_ms"] is None:
            empty_result = {"points": [], "sample_count": 0, "aggregation_seconds": 0}
            return empty_result if include_metadata else []

        first_ms = int(bounds["first_ms"])
        last_ms = int(bounds["last_ms"])
        span_ms = max(1, last_ms - first_ms + 1)
        dynamic_window_ms = (span_ms + config.HISTORY_MAX_POINTS - 1) // config.HISTORY_MAX_POINTS
        window_ms = max(window_ms, dynamic_window_ms)
        query_clauses = list(clauses)
        query_parameters = list(parameters)
        if end_ms is None:
            query_clauses.append("timestamp_ms <= ?")
            query_parameters.append(last_ms)
        query_where_clause = f"WHERE {' AND '.join(query_clauses)}" if query_clauses else ""
        averages = ", ".join(f"AVG({field}) AS {field}" for field in HISTORY_FIELDS)
        sql = f"""
            SELECT ((timestamp_ms - ?) / ?) * ? + ? AS bucket_ms,
                   COUNT(*) AS bucket_sample_count,
                   {averages}
            FROM samples
            {query_where_clause}
            GROUP BY bucket_ms
            ORDER BY bucket_ms ASC
        """
        with database_lock:
            rows = connection.execute(
                sql,
                (first_ms, window_ms, window_ms, first_ms, *query_parameters),
            ).fetchall()
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
    result = {
        "points": points,
        "sample_count": sum(row["bucket_sample_count"] for row in rows),
        "aggregation_seconds": window_ms / 1000,
    }
    return result if include_metadata else points


def _query_raw_statistics_segment(
    opened_connection: sqlite3.Connection,
    start_ms: int,
    end_ms: int,
) -> dict:
    statistics = _empty_statistics_state()
    sample_count = 0
    rows = opened_connection.execute(
        f"""
        SELECT {FIELD_COLUMNS}
        FROM samples
        WHERE timestamp_ms >= ? AND timestamp_ms <= ?
        ORDER BY timestamp_ms ASC, id ASC
        """,
        (start_ms, end_ms),
    )
    for row in rows:
        _consume_statistics_row(statistics, row)
        sample_count += 1
    return {"sample_count": sample_count, "statistics": statistics}


def _merge_statistics_segments(segments: list[dict]) -> dict:
    combined = _empty_statistics_state()
    sample_count = 0
    for segment in segments:
        if not segment["sample_count"]:
            continue
        sample_count += segment["sample_count"]
        for field in HISTORY_FIELDS:
            source = segment["statistics"][field]
            target = combined[field]
            if source["count"]:
                target["count"] += source["count"]
                target["sum"] += source["sum"]
                target["sum_squares"] += source["sum_squares"]
                target["min"] = (
                    source["min"]
                    if target["min"] is None
                    else min(target["min"], source["min"])
                )
                target["max"] = (
                    source["max"]
                    if target["max"] is None
                    else max(target["max"], source["max"])
                )

    result = {}
    for field, field_state in combined.items():
        if field_state["count"]:
            average = field_state["sum"] / field_state["count"]
            variance = max(
                0.0,
                field_state["sum_squares"] / field_state["count"] - average * average,
            )
            result[field] = {
                "min": field_state["min"],
                "max": field_state["max"],
                "average": average,
                "standard_deviation": math.sqrt(variance),
            }
    return {"sample_count": sample_count, "statistics": result}


def query_statistics(range_value: str, start: str | None = None, end: str | None = None):
    """Calculate exact statistics using hourly summaries plus raw boundary rows."""
    init_database()
    if connection is None:
        return None

    read_connection = None
    try:
        requested_start_ms = _parse_boundary(start)
        if requested_start_ms is None:
            range_start = _range_start(range_value)
            requested_start_ms = (
                round(range_start.timestamp() * 1000) if range_start else None
            )
        requested_end_ms = _parse_boundary(end)

        database_uri = pathlib.Path(config.DATABASE_FILE).resolve().as_uri() + "?mode=ro"
        read_connection = sqlite3.connect(
            database_uri,
            uri=True,
            timeout=5,
            check_same_thread=False,
        )
        read_connection.row_factory = sqlite3.Row
        read_connection.execute("PRAGMA query_only=ON")
        read_connection.execute("PRAGMA busy_timeout=5000")
        bounds = read_connection.execute(
            "SELECT MIN(timestamp_ms), MAX(timestamp_ms) FROM samples"
        ).fetchone()
        if bounds[0] is None:
            read_connection.close()
            return {"sample_count": 0, "statistics": {}}

        start_ms = max(
            int(bounds[0]),
            requested_start_ms if requested_start_ms is not None else int(bounds[0]),
        )
        end_ms = min(
            int(bounds[1]),
            requested_end_ms if requested_end_ms is not None else int(bounds[1]),
        )
        if start_ms > end_ms:
            read_connection.close()
            return {"sample_count": 0, "statistics": {}}

        first_full_bucket = ((start_ms + HOUR_MS - 1) // HOUR_MS) * HOUR_MS
        last_full_bucket = (((end_ms + 1) // HOUR_MS) - 1) * HOUR_MS
        segments = []
        if first_full_bucket > last_full_bucket:
            segments.append(
                _query_raw_statistics_segment(read_connection, start_ms, end_ms)
            )
        else:
            if start_ms < first_full_bucket:
                segments.append(
                    _query_raw_statistics_segment(
                        read_connection, start_ms, first_full_bucket - 1
                    )
                )

            summaries = {
                int(row["bucket_ms"]): {
                    "sample_count": int(row["sample_count"]),
                    "statistics": json.loads(row["statistics_json"]),
                }
                for row in read_connection.execute(
                    """
                    SELECT bucket_ms, sample_count, statistics_json
                    FROM hourly_statistics
                    WHERE bucket_ms >= ? AND bucket_ms <= ?
                    ORDER BY bucket_ms ASC
                    """,
                    (first_full_bucket, last_full_bucket),
                )
            }
            bucket_ms = first_full_bucket
            while bucket_ms <= last_full_bucket:
                segment = summaries.get(bucket_ms)
                if segment is None:
                    segment = _query_raw_statistics_segment(
                        read_connection, bucket_ms, bucket_ms + HOUR_MS - 1
                    )
                segments.append(segment)
                bucket_ms += HOUR_MS

            suffix_start_ms = last_full_bucket + HOUR_MS
            if suffix_start_ms <= end_ms:
                segments.append(
                    _query_raw_statistics_segment(
                        read_connection, suffix_start_ms, end_ms
                    )
                )

        result = _merge_statistics_segments(segments)
        read_connection.close()
        return result
    except (OSError, TypeError, ValueError, json.JSONDecodeError, sqlite3.Error) as error:
        _set_error("statistics query", error)
        if read_connection is not None:
            read_connection.close()
        return None


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


def stream_raw_history(
    range_value: str,
    start: str | None = None,
    end: str | None = None,
    batch_size: int = 1000,
):
    """Stream raw samples using a separate read-only WAL connection."""
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

        database_uri = pathlib.Path(config.DATABASE_FILE).resolve().as_uri() + "?mode=ro"
        read_connection = sqlite3.connect(
            database_uri,
            uri=True,
            timeout=5,
            check_same_thread=False,
        )
        read_connection.row_factory = sqlite3.Row
        read_connection.execute("PRAGMA query_only=ON")
        read_connection.execute("PRAGMA busy_timeout=5000")
        cursor = read_connection.execute(sql, parameters)
    except (OSError, TypeError, ValueError, sqlite3.Error) as error:
        _set_error("raw history stream", error)
        if "read_connection" in locals():
            read_connection.close()
        return None

    def generate_points():
        try:
            while rows := cursor.fetchmany(max(1, batch_size)):
                for row in rows:
                    point = {
                        "time": datetime.datetime.fromtimestamp(
                            row["timestamp_ms"] / 1000, datetime.timezone.utc
                        ).isoformat()
                    }
                    for field in HISTORY_FIELDS:
                        if row[field] is not None:
                            point[field] = row[field]
                    yield point
        except (OSError, sqlite3.Error) as error:
            _set_error("raw history stream", error)
            raise
        finally:
            cursor.close()
            read_connection.close()

    return generate_points()
