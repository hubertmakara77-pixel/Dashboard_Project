"""Reusable aggregation primitives for SQLite measurement statistics."""

import json
import math
import sqlite3
from collections.abc import Sequence
from typing import Any, TypedDict


class FieldAccumulator(TypedDict):
    """Numerically stable values retained while aggregation is in progress."""

    count: int
    sum: float
    sum_squares: float
    min: float | None
    max: float | None


class StatisticsSegment(TypedDict):
    """Raw or persisted aggregation segment consumed by the final merge."""

    sample_count: int
    statistics: dict[str, FieldAccumulator]


StatisticsState = dict[str, FieldAccumulator]


def empty_statistics_state(fields: Sequence[str]) -> StatisticsState:
    """Create mutable aggregation accumulators for every measurement field."""
    return {
        field: {
            "count": 0,
            "sum": 0.0,
            "sum_squares": 0.0,
            "min": None,
            "max": None,
        }
        for field in fields
    }


def consume_statistics_row(
    statistics: StatisticsState,
    row: sqlite3.Row,
    fields: Sequence[str],
) -> None:
    """Accumulate the numeric values from one SQLite row."""
    for field in fields:
        value = row[field]
        field_state = statistics[field]
        if value is None:
            continue
        numeric_value = float(value)
        field_state["count"] += 1
        field_state["sum"] += numeric_value
        field_state["sum_squares"] += numeric_value * numeric_value
        field_state["min"] = (
            numeric_value if field_state["min"] is None else min(field_state["min"], numeric_value)
        )
        field_state["max"] = (
            numeric_value if field_state["max"] is None else max(field_state["max"], numeric_value)
        )


def store_hourly_statistics(
    connection: sqlite3.Connection,
    bucket_ms: int,
    sample_count: int,
    statistics: StatisticsState,
) -> None:
    """Insert or replace one persistent hourly aggregation bucket."""
    connection.execute(
        """
        INSERT INTO hourly_statistics (bucket_ms, sample_count, statistics_json)
        VALUES (?, ?, ?)
        ON CONFLICT(bucket_ms) DO UPDATE SET
            sample_count = excluded.sample_count,
            statistics_json = excluded.statistics_json
        """,
        (bucket_ms, sample_count, json.dumps(statistics, separators=(",", ":"))),
    )


def rebuild_hourly_bucket(
    connection: sqlite3.Connection,
    bucket_ms: int,
    fields: Sequence[str],
    field_columns: str,
    hour_ms: int,
) -> None:
    """Recompute one hourly summary after samples in that hour change."""
    rows = connection.execute(
        f"""
        SELECT {field_columns}
        FROM samples
        WHERE timestamp_ms >= ? AND timestamp_ms < ?
        ORDER BY timestamp_ms ASC, id ASC
        """,
        (bucket_ms, bucket_ms + hour_ms),
    )
    statistics = empty_statistics_state(fields)
    sample_count = 0
    for row in rows:
        consume_statistics_row(statistics, row, fields)
        sample_count += 1
    if sample_count:
        store_hourly_statistics(connection, bucket_ms, sample_count, statistics)
    else:
        connection.execute("DELETE FROM hourly_statistics WHERE bucket_ms = ?", (bucket_ms,))


def backfill_hourly_statistics(
    connection: sqlite3.Connection,
    fields: Sequence[str],
    field_columns: str,
    hour_ms: int,
) -> None:
    """Build missing summaries for every completed historical hour."""
    bounds = connection.execute(
        "SELECT MIN(timestamp_ms), MAX(timestamp_ms) FROM samples"
    ).fetchone()
    if bounds[0] is None:
        return
    last_bucket_ms = (int(bounds[1]) // hour_ms) * hour_ms
    summarized_buckets = {
        row[0] for row in connection.execute("SELECT bucket_ms FROM hourly_statistics")
    }
    rows = connection.execute(
        f"""
        SELECT timestamp_ms, {field_columns}
        FROM samples
        WHERE timestamp_ms < ?
        ORDER BY timestamp_ms ASC, id ASC
        """,
        (last_bucket_ms,),
    )
    current_bucket = None
    current_count = 0
    statistics: StatisticsState | None = None
    for row in rows:
        bucket_ms = (int(row["timestamp_ms"]) // hour_ms) * hour_ms
        if bucket_ms != current_bucket:
            if current_bucket is not None and current_bucket not in summarized_buckets:
                assert statistics is not None
                store_hourly_statistics(connection, current_bucket, current_count, statistics)
            current_bucket = bucket_ms
            current_count = 0
            statistics = empty_statistics_state(fields)
        if bucket_ms not in summarized_buckets:
            assert statistics is not None
            consume_statistics_row(statistics, row, fields)
            current_count += 1
    if current_bucket is not None and current_bucket not in summarized_buckets:
        assert statistics is not None
        store_hourly_statistics(connection, current_bucket, current_count, statistics)


def query_raw_statistics_segment(
    connection: sqlite3.Connection,
    start_ms: int,
    end_ms: int,
    fields: Sequence[str],
    field_columns: str,
) -> StatisticsSegment:
    """Aggregate a raw inclusive time segment without persistent summaries."""
    statistics = empty_statistics_state(fields)
    sample_count = 0
    rows = connection.execute(
        f"""
        SELECT {field_columns}
        FROM samples
        WHERE timestamp_ms >= ? AND timestamp_ms <= ?
        ORDER BY timestamp_ms ASC, id ASC
        """,
        (start_ms, end_ms),
    )
    for row in rows:
        consume_statistics_row(statistics, row, fields)
        sample_count += 1
    return {"sample_count": sample_count, "statistics": statistics}


def merge_statistics_segments(
    segments: Sequence[StatisticsSegment],
    fields: Sequence[str],
) -> dict[str, Any]:
    """Merge raw and hourly segments into exact public statistics."""
    combined = empty_statistics_state(fields)
    sample_count = 0
    for segment in segments:
        if not segment["sample_count"]:
            continue
        sample_count += segment["sample_count"]
        for field in fields:
            source = segment["statistics"][field]
            target = combined[field]
            if source["count"]:
                source_min = source["min"]
                source_max = source["max"]
                assert source_min is not None and source_max is not None
                target["count"] += source["count"]
                target["sum"] += source["sum"]
                target["sum_squares"] += source["sum_squares"]
                target["min"] = (
                    source_min if target["min"] is None else min(target["min"], source_min)
                )
                target["max"] = (
                    source_max if target["max"] is None else max(target["max"], source_max)
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
