# Troubleshooting

## Diagnostic order

Start with nondestructive checks:

```console
sudo amp-panel doctor
sudo amp-panel status
sudo amp-panel logs -n 200
sudo amp-panel paths
```

Do not change the port, profile, and cabling at the same time. One change at a
time makes the cause identifiable and prevents several problems from overlapping.

## The dashboard does not open

1. Check `amp-panel status` and the port stored in
   `/etc/amp-panel/amp-panel.env`.
2. Try the IP address instead of `<name>.local`; mDNS requires Avahi and client
   support.
3. Verify that the application port is reachable and not blocked by a firewall.
4. Inspect `amp-panel logs`; an import-time configuration error stops the service.

The web port must be in the range 1024–65535. After a manual file change, always
rerun the configurator or restart the service.

## Login fails

| Message | Most likely cause |
| --- | --- |
| Invalid username or password | user absent from the local list, inactive, or rejected by RADIUS |
| Authentication server is unavailable | connectivity, address, secret, timeout, or RADIUS outage |
| Too many login attempts | per-IP limit reached; wait for the configured window |
| 401 after earlier use | session expired or was lost after a restart |

Verify that the local name matches the RADIUS identity, UDP 1812 is reachable,
the shared secret is correct, and the NAS identifier is expected. If the
dashboard is behind a reverse proxy, set `TRUST_PROXY_HEADERS=true` only for a
trusted proxy; otherwise a client header could spoof the source IP.

## No serial connection

```console
ls -l /dev/serial/by-id /dev/ttyACM* /dev/ttyUSB*
sudo amp-panel doctor
sudo amp-panel logs -f
```

Check the cable, device power, port name, service membership in `dialout`, and
whether another process owns the port. Typical baud rates are 9600 for the
amplifier and 115200 for FTS-LS. After correcting the setting:

```console
sudo amp-panel configure
sudo amp-panel restart
```

FTS-LS also requires a valid station-console username and password. Station
authentication errors are unrelated to RADIUS.

## Connected, but data is empty

For the amplifier, verify that the device emits newline-terminated frames in the
format described in [device protocols](../technical/protocols.md). Unknown fields
are ignored, but a database record requires at least one supported numeric field.

For FTS-LS, `show status` must contain UL/Uplink or a P1–P7 port. The dashboard
also queries every detailed section. An incomplete response or changed prompt may
cause the session to reconnect.

## Database problems

If `doctor` reports an integrity error:

1. stop the service;
2. back up all `measurements.db*` files;
3. do not migrate the directory or reduce the record limit;
4. check free space and storage-device system logs;
5. perform recovery on a copy according to SQLite procedures.

A `degraded` API state means the latest database operation failed.
`DATABASE_MAX_RECORDS=0` does not protect against a full disk; it only disables
the record-count limit.

## Alarm history disappeared

Alarm history is read from the syslog file and its rotations, not from SQLite.
Check `SYSLOG_EXPORT_FILE`, rsyslog configuration, `adm` group permissions,
rotation, and `.gz` files. Current active alarms reside in process memory. After
a restart, the active list is rebuilt from new measurements.

## A network change did not persist

This is expected if the new address was not confirmed within 60 seconds or the
confirmation arrived through another interface. After rollback, reconnect to the
old address and check `amp-panel-network-agent.service`. Do not bypass the
checkpoint by calling the agent endpoint manually.

## SNMP does not respond

Verify that SNMP is enabled in the dashboard, check the UDP port (1161 by
default), community, and firewall. The UI port must match `SNMP_PORT`. A community
shorter than 12 characters is rejected. `tools/snmp_probe.py` is available for
repository-level testing.

## Problem report

Include the version (`amp-panel version`), profile, `doctor` output, the last 200
log lines, the incident time, and preceding changes. Remove secrets, community
strings, cookies, and FTS-LS/RADIUS passwords before sharing the material.
