# Administrator manual

## Responsibilities

An Administrator manages the local access list, host network, service
diagnostics, SNMP, and FTS-LS administrative operations. User passwords are not
managed by the dashboard; credentials and password policy belong to RADIUS.

## Users and roles

On **Access Control**, add a username, assign a role, and enable or disable its
local account. The name must match the RADIUS identity. Allowed characters are
letters, digits, `.`, `_`, `@`, and `-`; the length must be 1–128 characters.

The system prevents accidental administrative lockout:

- the only user cannot be deleted;
- the last active Administrator cannot be deleted, disabled, or demoted;
- no password is stored in `persisted_state.json`.

Installation creates an active Administrator named by
`INITIAL_ADMIN_USERNAME`. The first login succeeds only if that same username and
password are accepted by the configured RADIUS server.

## Network configuration

**Network Configuration** supports DHCP and static IPv4. For a static address,
provide the interface, address, netmask, gateway, and DNS. The gateway must be in
the same subnet as the interface address.

After applying settings:

1. the privileged agent creates a NetworkManager checkpoint;
2. it activates the new settings;
3. the dashboard receives a token valid for 60 seconds;
4. the browser must reconnect at the new address and confirm the change;
5. lack of confirmation triggers automatic rollback.

Confirmation must arrive through the changed interface. Do not change the
network without local access or a known recovery path. Only one unconfirmed
change may exist at a time.

## Service Diagnostics

The screen reports:

- serial port, baud rate, and connection state;
- database file, state, record count, and size;
- free space, sampling rate, and estimated retention;
- local and remote syslog plus heartbeat interval.

An Administrator can change the USB port, heartbeat, and record limit. Heartbeat
may be `0` (disabled) or 10–86400 seconds. The database limit may be `0`
(unlimited) or 1–10,000,000. Lowering the limit immediately deletes the oldest
records and cannot be undone.

Changing the port from the UI is limited to currently visible
`/dev/ttyACM*` or `/dev/ttyUSB*` devices. A persistent
`/dev/serial/by-id/...` path can be selected with `amp-panel configure`.

## SNMP

**SNMP Configuration** enables the agent and configures its community and trap
destination. The agent port is fixed by server configuration (UDP 1161 by
default), and the community must contain at least 12 characters. Saving restarts
the SNMP agent. The full OID map is in [integrations](../technical/integrations.md).

## NTP and syslog

**Time Diagnostics** queries the configured NTP server; forcing a refresh bypasses
the cache. **Service Diagnostics** can download the current syslog file. Audit
events include logins, setting and user changes, network, SNMP, exports, and
FTS-LS commands.

## Post-change verification

After every administrative change, verify:

1. the dashboard still responds and the session is active;
2. **Live View** receives new data;
3. `sudo amp-panel doctor` exits with code 0;
4. no new error appears in the logs;
5. the change remains in effect after a service restart.
