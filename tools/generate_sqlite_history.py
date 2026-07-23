#!/usr/bin/env python3
"""Generate realistic optical-amplifier history in the dashboard SQLite schema.

This is a fast historical data generator, not a benchmark of the application's
one-sample-at-a-time write path. It builds the same final tables and indexes,
but inserts rows in batches so that weeks of data can be created in minutes.
"""

from __future__ import annotations

import argparse
import datetime
import pathlib
import shutil
import sqlite3
import sys
import time


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
BYTES_PER_RECORD_ESTIMATE = 240
RESERVED_FREE_BYTES = 512 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate dashboard-compatible SQLite measurement history."
    )
    parser.add_argument("--days", type=float, default=30.0)
    parser.add_argument("--interval-ms", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=50_000)
    parser.add_argument(
        "--max-records",
        type=int,
        default=0,
        help="Keep only this many newest samples; 0 stores the full period.",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path.home() / "sqlite_stress" / "measurements_30d.db",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing output database.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> tuple[int, int]:
    if args.days <= 0:
        raise ValueError("--days must be greater than zero")
    if args.interval_ms <= 0:
        raise ValueError("--interval-ms must be greater than zero")
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be greater than zero")
    if args.max_records < 0:
        raise ValueError("--max-records cannot be negative")

    theoretical_records = round(args.days * 86_400_000 / args.interval_ms)
    stored_records = (
        min(theoretical_records, args.max_records)
        if args.max_records
        else theoretical_records
    )
    if stored_records <= 0:
        raise ValueError("selected parameters produce no records")
    return theoretical_records, stored_records


def ensure_output_is_safe(
    path: pathlib.Path,
    stored_records: int,
    overwrite: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists; use --overwrite to replace it")

    estimated_bytes = stored_records * BYTES_PER_RECORD_ESTIMATE
    free_bytes = shutil.disk_usage(path.parent).free
    required_bytes = estimated_bytes + RESERVED_FREE_BYTES
    if free_bytes < required_bytes:
        raise OSError(
            "not enough free space: "
            f"estimated requirement {required_bytes / 1024**3:.2f} GiB, "
            f"available {free_bytes / 1024**3:.2f} GiB"
        )

    if path.exists():
        path.unlink()
    for suffix in ("-wal", "-shm"):
        companion = pathlib.Path(f"{path}{suffix}")
        if companion.exists():
            companion.unlink()


def create_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE samples (
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
        );

        CREATE TABLE setpoint_events (
            id INTEGER PRIMARY KEY,
            timestamp_ms INTEGER NOT NULL,
            gain_set REAL NOT NULL
        );

        CREATE TABLE database_metadata (
            key TEXT PRIMARY KEY,
            value INTEGER NOT NULL
        ) WITHOUT ROWID;
        """
    )


def sample_row(sequence: int, timestamp_ms: int) -> tuple[float | int | None, ...]:
    # Deterministic variation keeps generation fast and makes gaps/reordering
    # visible without requiring a random-number generator.
    slow = (sequence % 20_000) / 20_000.0
    fast = ((sequence % 200) - 100) / 100.0
    gain_set = 13.5 if (sequence // 216_000) % 2 == 0 else 14.0
    gain_actual = gain_set + fast * 0.08
    gain_delta = gain_set - gain_actual
    pi_a = -23.5 + slow * 1.2 + fast * 0.03
    pi_b = pi_a - 1.6 + fast * 0.02
    po_a = pi_a + gain_actual
    po_b = pi_b + gain_actual
    temperature = 35.0 + slow * 2.5 + fast * 0.04

    return (
        timestamp_ms,
        None,
        round(pi_a, 3),
        round(po_a, 3),
        round(pi_b, 3),
        round(po_b, 3),
        None,
        None,
        None,
        None,
        gain_set,
        round(gain_actual, 3),
        round(gain_delta, 3),
        round(temperature, 3),
        float(sequence),
    )


def generate_samples(
    connection: sqlite3.Connection,
    first_sequence: int,
    stored_records: int,
    first_timestamp_ms: int,
    interval_ms: int,
    batch_size: int,
) -> None:
    placeholders = ", ".join("?" for _ in range(15))
    insert_sql = f"""
        INSERT INTO samples (
            timestamp_ms, {', '.join(HISTORY_FIELDS)}
        ) VALUES ({placeholders})
    """
    started = time.monotonic()
    inserted = 0

    while inserted < stored_records:
        current_batch_size = min(batch_size, stored_records - inserted)
        batch = []
        for offset in range(current_batch_size):
            local_index = inserted + offset
            sequence = first_sequence + local_index
            timestamp_ms = first_timestamp_ms + local_index * interval_ms
            batch.append(sample_row(sequence, timestamp_ms))

        with connection:
            connection.executemany(insert_sql, batch)
        inserted += current_batch_size

        elapsed = max(time.monotonic() - started, 0.001)
        rate = inserted / elapsed
        remaining_seconds = (stored_records - inserted) / rate
        percent = inserted * 100 / stored_records
        print(
            f"\r{inserted:,}/{stored_records:,} ({percent:5.1f}%) "
            f"{rate:,.0f} rows/s, ETA {remaining_seconds:,.0f}s",
            end="",
            flush=True,
        )
    print()


def add_setpoint_events(
    connection: sqlite3.Connection,
    start_timestamp_ms: int,
    total_period_records: int,
    interval_ms: int,
) -> None:
    period_ms = total_period_records * interval_ms
    event_interval_ms = 6 * 60 * 60 * 1000
    events = []
    offset_ms = 0
    event_index = 0
    while offset_ms < period_ms:
        gain_set = 13.5 if event_index % 2 == 0 else 14.0
        events.append((start_timestamp_ms + offset_ms, gain_set))
        offset_ms += event_interval_ms
        event_index += 1
    with connection:
        connection.executemany(
            "INSERT INTO setpoint_events (timestamp_ms, gain_set) VALUES (?, ?)",
            events,
        )


def finalize_schema(connection: sqlite3.Connection, sample_count: int) -> None:
    with connection:
        connection.execute(
            "CREATE INDEX idx_samples_timestamp ON samples (timestamp_ms)"
        )
        connection.execute(
            "CREATE INDEX idx_setpoints_timestamp ON setpoint_events (timestamp_ms)"
        )
        connection.execute(
            "INSERT INTO database_metadata (key, value) VALUES ('sample_count', ?)",
            (sample_count,),
        )
        connection.executescript(
            """
            CREATE TRIGGER samples_count_after_insert
            AFTER INSERT ON samples
            BEGIN
                UPDATE database_metadata SET value = value + 1
                WHERE key = 'sample_count';
            END;

            CREATE TRIGGER samples_count_after_delete
            AFTER DELETE ON samples
            BEGIN
                UPDATE database_metadata SET value = value - 1
                WHERE key = 'sample_count';
            END;

            PRAGMA user_version=2;
            """
        )


def main() -> int:
    args = parse_args()
    try:
        theoretical_records, stored_records = validate_args(args)
        output = args.output.expanduser().resolve()
        ensure_output_is_safe(output, stored_records, args.overwrite)
    except (ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    end_timestamp_ms = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
    full_start_timestamp_ms = end_timestamp_ms - theoretical_records * args.interval_ms
    first_sequence = theoretical_records - stored_records
    first_timestamp_ms = full_start_timestamp_ms + first_sequence * args.interval_ms

    print(f"Output:              {output}")
    print(f"Simulated period:    {args.days:g} days")
    print(f"Sample interval:     {args.interval_ms} ms")
    print(f"Theoretical samples: {theoretical_records:,}")
    print(f"Stored samples:      {stored_records:,}")
    print(
        "Estimated size:      "
        f"{stored_records * BYTES_PER_RECORD_ESTIMATE / 1024**3:.2f} GiB"
    )

    connection = sqlite3.connect(output)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("PRAGMA cache_size=-65536")
        create_tables(connection)
        generate_samples(
            connection,
            first_sequence,
            stored_records,
            first_timestamp_ms,
            args.interval_ms,
            args.batch_size,
        )
        add_setpoint_events(
            connection,
            full_start_timestamp_ms,
            theoretical_records,
            args.interval_ms,
        )
        print("Creating indexes and triggers...")
        finalize_schema(connection, stored_records)
        result = connection.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise sqlite3.DatabaseError(f"quick_check returned: {result}")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()

    size_bytes = output.stat().st_size
    with sqlite3.connect(output) as verification_connection:
        newest_row = verification_connection.execute(
            "SELECT datetime(timestamp_ms / 1000.0, 'unixepoch'), "
            "PiA, PoA, gain_actual, temperature "
            "FROM samples ORDER BY id DESC LIMIT 1"
        ).fetchone()

    print(f"Finished: {size_bytes / 1024**3:.2f} GiB")
    print("Integrity check: ok")
    print(f"Newest row: {newest_row!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
