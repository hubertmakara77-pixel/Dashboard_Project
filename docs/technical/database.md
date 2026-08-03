# Database

## Engine and operating mode

The application uses SQLite in WAL mode (`journal_mode=WAL`) with
`synchronous=NORMAL`. The default path is
`/var/lib/amp-panel/measurements.db`. Shutdown runs
`wal_checkpoint(TRUNCATE)`.

## Schema version 5

| Table | Purpose |
| --- | --- |
| `samples` | amplifier measurements with UTC time in `timestamp_ms` |
| `setpoint_events` | `gain_set` setpoint history |
| `hourly_statistics` | precomputed full-hour aggregates stored as JSON |
| `device_snapshots` | complete profile snapshots, currently FTS-LS, stored as canonical JSON |
| `database_metadata` | record counters maintained by triggers |

`samples` contains `M`, `PiA`, `PoA`, `PiB`, `PoB`, `G`, `SG`, `PP`, `SPP`,
`gain_set`, `gain_actual`, `gain_delta`, `temperature`, and `seq_nr`. A missing or
nonnumeric value is stored as `NULL`. Time is normalized to UTC.

## History and statistics

Amplifier ranges are `5m`, `1h`, `24h`, `7d`, `30d`, and `all`. `start` and `end`
are ISO 8601 timestamps; a timestamp without a zone is interpreted as UTC. The
history view limits points to `HISTORY_MAX_POINTS` (programmatic minimum 100) and
returns reduction metadata. CSV export streams raw records.

Statistics combine raw data from incomplete boundary hours with persisted
aggregates for complete hours. Long ranges therefore do not require scanning
every sample. Inserting a historical sample rebuilds the affected aggregate.

FTS-LS snapshots use the same ranges and an HTTP limit of up to 10,000 per
request. Each snapshot stores a stable station object rather than unrelated
individual measurements.

## Retention

`DATABASE_MAX_RECORDS=0` means unlimited records. A positive value deletes the
oldest records after each write:

- for `amplifier`, the limit applies to `samples`;
- for `fts-ls`, it applies to snapshots for that profile.

Deletion increments the process's discarded-record counter and sends a syslog
warning. Reducing the limit in diagnostics applies it immediately.
`setpoint_events` are not included in the sample limit.

## Migrations

Schema creation is idempotent at startup. A legacy `measurements` table containing
`fields_json` and `timestamp_epoch` is migrated to columnar `samples`; records of
type `optical_amp_setpoint` are moved to `setpoint_events`. Older schemas rebuild
hourly aggregates and set `PRAGMA user_version` to 5.

## Diagnostic state

The API reports state, the last operation error, record count, combined DB/WAL/SHM
size, free space, growth rate, and estimated time to the configured limit or disk
exhaustion. These are estimates based on existing records, not retention
guarantees.
