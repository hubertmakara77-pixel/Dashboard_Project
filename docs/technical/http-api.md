# HTTP API

## Common rules

The API is served by the same host as the dashboard. Successful login sets a
`session_token` cookie, which subsequent requests must send. Requests and
responses use JSON except for CSV and log exports. Timestamps use ISO 8601, and
history data is normalized to UTC.

Typical status codes:

- `400` — invalid value or range;
- `401` — missing or expired session;
- `403` — insufficient role;
- `409` — state conflict, missing confirmation, or wrong device profile;
- `429` — login or concurrent-export limit;
- `503` — device, database, RADIUS, or system agent unavailable.

FastAPI's interactive documentation is not presented as a dashboard feature, but
the request-model contracts are described below.

## Authentication and access control

| Method and path | Role | Request / result |
| --- | --- | --- |
| `POST /api/auth/login` | public | `{username,password}` → `{user}` plus cookie |
| `GET /api/auth/me` | any | current user |
| `POST /api/auth/logout` | any | invalidates session and cookie |
| `GET /api/access/users` | Administrator | local user list |
| `POST /api/access/users` | Administrator | `{username,role,active}` |
| `PUT /api/access/users/{username}` | Administrator | optional `{role,active}` |
| `DELETE /api/access/users/{username}` | Administrator | removes local entry |

Example `curl` session:

```console
curl -c cookies.txt -H 'Content-Type: application/json' \
  -d '{"username":"operator","password":"..."}' \
  http://panel.local:8000/api/auth/login
curl -b cookies.txt http://panel.local:8000/api/latest
```

The cookie file is a session secret. Do not commit it or attach it to reports.

## Status, settings, and alarms

| Method and path | Role | Description |
| --- | --- | --- |
| `GET /api/latest` | Viewer+ | profile, connection, error, time, data, and DB state |
| `GET /api/settings` | Viewer+ | thresholds, tolerance, and setpoint bounds |
| `POST /api/settings` | Operator+ | changes alarm tolerance and thresholds |
| `GET /api/errors` | Viewer+ | compatibility view of active alarms |
| `GET /api/warnings` | Viewer+ | active and historical alarms with filters |
| `POST /api/warnings/acknowledge` | Operator+ | acknowledges all active alarms |
| `POST /api/errors/clear` | Operator+ | compatibility alias for acknowledgement |
| `POST /api/set_gain` | Operator+ | `{gain_set:number}`; amplifier only |

`GET /api/warnings` accepts `range=session|1h|24h|7d|30d|custom`, `start`, `end`,
`field`, `status=open|cleared`, `limit` 1–500, and `offset` 0–10000. `start` is
required for `custom`.

`POST /api/settings` accepts optional `gain_tolerance` and `warn_limits`. Limits
have the shape `{"PiA":{"min":null,"max":null}, ...}`. Allowed fields are PiA,
PoA, PiB, PoB, and temperature.

## Amplifier history

| Method and path | Role | Description |
| --- | --- | --- |
| `GET /api/history` | Viewer+ | chart points and reduction metadata |
| `GET /api/statistics` | Viewer+ | count/min/max/average for fields |
| `GET /api/history/export.csv` | Viewer+ | streaming export of raw records |

Parameters are `range=5m|1h|24h|7d|30d|all` and optional ISO 8601 `start` and
`end`. `start` must precede `end`. Only one CSV export may run at a time; a second
request receives `429`.

## FTS-LS

These endpoints return `409` unless `DEVICE_PROFILE=fts-ls`.

| Method and path | Role | Description |
| --- | --- | --- |
| `GET /api/fts-ls/capabilities` | Viewer+ | controls and ranges |
| `GET /api/fts-ls/status` | Viewer+ | connection and stable station snapshot |
| `POST /api/fts-ls/command` | Operator+ | allowlisted safe command |
| `GET /api/fts-ls/history` | Viewer+ | station snapshots |
| `GET /api/fts-ls/history/export.csv` | Viewer+ | flattened CSV |

Command request:

```json
{
  "action": "laser_central_frequency",
  "parameters": {"value": 194400.0},
  "confirmed": true
}
```

Actions and confirmation rules are listed in the
[FTS-LS manual](../manual/fts-ls.md). History accepts standard `range`, `start`,
and `end`, plus `limit` from 1 to 10000 (default 2000, export default 10000).

## Diagnostics and integrations

| Method and path | Role | Description |
| --- | --- | --- |
| `GET /api/service-diagnostics` | Administrator | serial, DB, and syslog status |
| `PUT /api/service-diagnostics/settings` | Administrator | heartbeat, DB limit, serial port |
| `GET /api/network` | Administrator | NetworkManager state |
| `POST /api/network` | Administrator | applies a checkpointed change |
| `POST /api/network/confirm` | Administrator | confirms the change token |
| `GET /api/ntp/status?force=false` | Administrator | NTP status |
| `GET /api/syslog/export.log` | Administrator | downloads the current log |
| `GET /api/snmp/live_data` | Viewer+ | current data published through SNMP |
| `GET /api/snmp/settings` | Administrator | agent/trap settings |
| `POST /api/snmp/settings` | Administrator | saves and restarts SNMP |

Service-settings model:

```json
{
  "syslog_heartbeat_seconds": 300,
  "database_max_records": 0,
  "serial_port": "/dev/ttyACM0"
}
```

The network model contains `interface`, `mode` (`dhcp` or `static`), `ip_address`,
`netmask`, `gateway`, and `dns`. A change response includes
`confirmation.token` and `expires_in_seconds=60`; confirm with
`{"token":"..."}`.

The SNMP model contains `enabled`, `port`, `community`, `trap_host`, and
`trap_port`. The port must equal `SNMP_PORT`, and the community must contain at
least 12 characters.

## Contract stability

Response fields may be added without changing the path. Consumers should ignore
unknown fields and must not depend on JSON key order. Removing or changing the
meaning of a field, range, or permission requires updates to documentation, API
tests, and the frontend client.
