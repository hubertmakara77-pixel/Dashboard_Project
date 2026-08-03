# System integrations

## RADIUS

RADIUS is responsible only for password verification. The dashboard's local list
determines who may attempt login and which role they receive. Defaults are UDP
1812, a 3-second timeout, and one retry. `RADIUS_NAS_IDENTIFIER` defaults to the
device name.

## Syslog

The application sends local syslog over UDP, by default to `127.0.0.1:514`, with
facility 16 (`local0`). Rsyslog writes `/var/log/amp-panel/amp-panel.log` and can
forward it remotely over TCP or UDP. Message categories:

- `lifecycle` — startup, shutdown, and heartbeat;
- `warning` — `OPEN`, `CLEARED`, and retention warnings;
- `audit` — user and administrator actions.

Alarm history also reads numeric rotations and `.gz` files. Remote syslog is not
the source used by the dashboard's alarm history; the local export file is
required.

## SNMP

The agent exposes private enterprise tree `1.3.6.1.4.1.99999`. The default port
is UDP 1161. Alarm traps use OID `1.3.6.1.4.1.99999.4.1` and default destination
port 162.

### Common and amplifier OIDs

| OID suffix after `...99999` | Value |
| --- | --- |
| `.1.1.0` | overall connection status |
| `.2.1.0` | PiA |
| `.2.2.0` | PoA |
| `.2.3.0` | PiB |
| `.2.4.0` | PoB |
| `.2.5.0` | actual gain |
| `.2.6.0` | gain setpoint |
| `.2.7.0` | gain delta |
| `.2.8.0` | temperature |
| `.2.9.0` | sequence number |

### FTS-LS OIDs

| OID | Value |
| --- | --- |
| `.3.1.0` | profile |
| `.3.2.0` | laser state |
| `.3.3.0` | optical frequency |
| `.3.4.0` | TEC temperature |
| `.3.5.0`, `.3.6.0` | power A/B |

UL and P1–P7 modules are under `.3.10.<index>.<field>`, where index `0` means UL
and `1`–`7` means a port. Fields are: `1` state, `2` type, `3` optical power, `4`
LF noise, `5` HF noise, and `6` jitter.

Changing the community or enabled state restarts the in-process agent. SNMP v2c
does not provide encryption; restrict access at the network layer.

## NTP

The default server is `tempus1.gum.gov.pl`, with fallback IP
`194.146.251.100`, UDP 123, a 3-second timeout, and a 15-second cache. The
diagnostic endpoint measures the response independently from system-clock
configuration; the package generates `systemd-timesyncd` configuration.

## mDNS

The package configures Avahi and `<MDNS_HOSTNAME>.local`. The configured label is
at most 63 characters, uses lowercase letters, digits, and hyphens, and excludes
the `.local` suffix. mDNS is a discovery mechanism, not a replacement for DNS or
stable production addressing.
