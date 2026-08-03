# Roles and permissions

`Viewer+` means Viewer, Operator, or Administrator. `Operator+` means Operator or
Administrator.

| Function | Viewer | Operator | Administrator |
| --- | :---: | :---: | :---: |
| Live View and read-only settings | ✓ | ✓ | ✓ |
| History, statistics, and CSV | ✓ | ✓ | ✓ |
| Alarm list and live SNMP data | ✓ | ✓ | ✓ |
| Gain/threshold changes and alarm acknowledgement | — | ✓ | ✓ |
| Operational FTS-LS control | — | ✓ | ✓ |
| FTS-LS reboot/power reset/factory default | — | — | ✓ |
| User list and management | — | — | ✓ |
| Network, NTP, and service diagnostics | — | — | ✓ |
| SNMP configuration and syslog export | — | — | ✓ |

## Endpoint matrix

| Level | Endpoints |
| --- | --- |
| Viewer+ | `GET /api/latest`, `/api/settings`, `/api/errors`, `/api/warnings`, `/api/history`, `/api/statistics`, `/api/history/export.csv`, `/api/snmp/live_data`, `/api/fts-ls/capabilities`, `/status`, `/history`, `/history/export.csv` |
| Operator+ | `POST /api/settings`, `/api/warnings/acknowledge`, `/api/errors/clear`, `/api/set_gain`, `/api/fts-ls/command` except admin actions |
| Administrator | `/api/access/users*`, `/api/service-diagnostics*`, `/api/network*`, `/api/ntp/status`, `/api/syslog/export.log`, `/api/snmp/settings`, and FTS-LS admin actions |

Every role may call `GET /api/auth/me` and `POST /api/auth/logout` after login.
Login is public but requires an active local entry and successful RADIUS
authentication.

## Role meaning

- **Viewer** — supervision without changing the device or configuration.
- **Operator** — everyday process operation and alarm response.
- **Administrator** — access security, host system, and maintenance operations.

Apply least privilege: a permanent dashboard display should use Viewer, and
everyday operation should not use an Administrator account.
