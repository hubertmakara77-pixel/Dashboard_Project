# Architecture

## Data flow

```text
serial device
    │
    ▼
serial.py or fts_ls.py worker ──► live state protected by state_lock
    │                                      │
    ▼                                      ▼
SQLite history                         FastAPI /api/*
                                           │
                                           ▼
                                  HTML + JavaScript dashboard

alarms ──► syslog/rotation ──► alarm history
      └──► SNMP trap
```

At startup, the FastAPI process initializes the database and SNMP, starts one
serial communication thread, and starts the syslog heartbeat task. During a
controlled shutdown, it sends a lifecycle event, stops the worker, closes SNMP,
and checkpoints SQLite.

## Backend boundaries

- `app/api` — HTTP routing, request models, role checks, and error translation;
- `app/core` — configuration, validation, shared state, and contract types;
- `app/services` — device protocols, SQLite, RADIUS, SNMP, syslog, NTP, and
  networking;
- `tools` — package CLI, privileged network agent, and service utilities;
- `templates` and `static` — the interface without a bundling step.

## Hardware adaptation boundary

Firmware-facing names and syntax are intentionally separated from application
contracts:

- `app/protocols/amplifier.py` owns amplifier frame delimiters, raw field aliases,
  missing-value handling, and outbound command formatting;
- `app/protocols/fts_ls.py` owns FTS-LS prompts, polling commands, raw section
  labels, value normalization, and outbound command construction;
- `app/core/device_schema.py` defines canonical field names, labels, history order,
  warning fields, and stable SNMP field assignments.

Services consume canonical values only. The database, HTTP API, SNMP, and
frontend must never depend on a spelling observed directly in firmware output.
When firmware changes a label, add an alias in the corresponding protocol adapter
and add a captured-response test; do not rename the canonical field.

The API layer should not build device commands or SQL queries. The serial worker
is the sole owner of the physical connection. FTS-LS commands pass through a
bounded queue so HTTP traffic cannot create unbounded work.

## Concurrency

`state.state_lock` protects shared settings and live data. `state.serial_lock`
protects the serial-port handle. SQLite uses `database_lock` and transactions;
long history reads use separate connections so they do not block the primary
writer. Only one raw amplifier CSV export can run at a time.

## Frontend

Classic scripts are loaded in a defined order:

1. `dashboard-core.js` — state, formatting, and common UI;
2. `dashboard-network.js` — network and diagnostics;
3. `dashboard.js` — authentication, settings, alarms, and access control;
4. `dashboard-history.js` — history, statistics, and charts;
5. `dashboard-fts-ls.js` — FTS-LS control and mapping;
6. `dashboard-bootstrap.js` — startup, refresh, and timers.

Avoiding a bundler simplifies offline deployment. Consequently, inter-file
dependencies form a contract. Shared structures should have JSDoc, and a new
script must be added both to the template and to static-asset version hashing.

## System processes and privileges

`amp-panel.service` runs without root as `amp-panel`, with supplementary
`dialout` and `adm` groups and systemd hardening. The
`amp-panel-network-agent.service` runs as root but listens only on the controlled
Unix socket `/run/amp-panel/network-agent.sock`. Its API is limited to reading,
checkpointed application, and confirmation of NetworkManager settings.

## Persistence

`amp-panel.env` is host configuration. `persisted_state.json` stores settings
changed in the UI. `measurements.db` stores measurements, setpoints, hourly
statistics, and profile snapshots. Alarm history belongs to syslog to preserve an
audit trail and cooperate with system log rotation.
