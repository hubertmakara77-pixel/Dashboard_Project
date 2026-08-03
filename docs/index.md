# Amp Panel documentation

This documentation describes the application version contained in this
repository. It covers Debian package installation, host configuration, everyday
dashboard operation, integrations, and the technical contracts of both device
profiles.

## Choose the right document

| Need | Document |
| --- | --- |
| First login and device check | [Quick start](manual/quick-start.md) |
| Monitoring, alarms, history, and export | [Operator manual](manual/operator.md) |
| Laser station control | [FTS-LS station](manual/fts-ls.md) |
| Users, network, SNMP, and diagnostics | [Administrator manual](manual/administrator.md) |
| Device installation or upgrade | [Installation](operations/installation.md) |
| Failure or missing data | [Troubleshooting](operations/troubleshooting.md) |
| API integration | [HTTP API](technical/http-api.md) |
| Application development | [Environment and tests](development.md) |

## Device profiles

The profile is selected during configuration and stored as `DEVICE_PROFILE`.

| Profile | Default link | Data and control |
| --- | --- | --- |
| `amplifier` | 9600 bit/s, serial port | PiA, PoA, PiB, PoB, gain, temperature, and gain setpoint |
| `fts-ls` | 115200 bit/s, serial console | laser, synthesizer, TEC, UL, P1–P7, power, and station commands |

Changing the profile requires reconfiguration and a service restart. Data from
both profiles can reside in the same database, but the user interface and active
API depend on the profile selected at startup.

## Important operational rules

1. A user must exist in the local access list, but the password is verified by
   the configured RADIUS server. The dashboard does not store operator passwords.
2. A positive record limit permanently deletes the oldest data after the limit is
   exceeded. A value of `0` means no record-count limit.
3. Network configuration changes must be confirmed within 60 seconds. Otherwise,
   NetworkManager automatically restores the previous settings.
4. FTS-LS `power reset`, `factory default`, and `reboot` are available only to an
   Administrator. Transfer-affecting operations require an additional explicit
   confirmation in the interface.
5. Acknowledging an alarm does not remove its cause. The alarm closes only after
   the measurement returns to a valid state.

## Source of truth

The documentation describes public application behavior. When an endpoint,
environment variable, control range, or data format changes, update the relevant
chapter in the same change and run `mkdocs build --strict`.
