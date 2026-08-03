# FTS-LS station operation

## Screen scope

The FTS-LS screen shows the laser, TEC, external 10 MHz reference,
synthesizer, power supplies, UL, and P1–P7 status. Available controls are returned
by `GET /api/fts-ls/capabilities`, allowing the interface to use the ranges
configured on the server.

## Permissions and confirmations

| Action | Minimum role | Requires confirmation |
| --- | --- | --- |
| Ping | Operator | no |
| Module description, distance, gain, polarization, TEC | Operator | depends on the action; see below |
| Laser power, central frequency, mode, force re-lock | Operator | yes |
| Module optical power | Operator | yes |
| Reboot | Administrator | administrative UI confirmation |
| Power reset | Administrator | yes |
| Factory default | Administrator | yes |

The backend always requires `confirmed=true` for `laser_power`,
`laser_central_frequency`, `laser_mode`, `laser_force_relock`, `optical_power`,
`power_reset`, and `factory_default`. Hiding a button in the UI is not a security
control; the API verifies the permission again.

## Laser

- **Power** turns the laser on or off and may interrupt transfer.
- **Central frequency** accepts GHz. The default application range is
  194392.6–194405.6 GHz, but the final range comes from host configuration.
- **Mode** selects an allowed station mode.
- **Frequency span** accepts 100–10,000 MHz.
- **Force re-lock** forces resynchronization and may briefly interrupt operation.

After a change, wait for the next complete status poll. The command result appears
as `last_command`, but only a new status snapshot confirms the device state.

## Command API parameters

The dashboard uses the following `parameters` contract. It also applies to
integrators calling `POST /api/fts-ls/command` directly.

| `action` | `parameters` | Validation |
| --- | --- | --- |
| `laser_power` | `enabled: bool` | — |
| `laser_central_frequency` | `value: number` | configured GHz range |
| `laser_mode` | `value` | `normal` or `central-frequency` |
| `laser_frequency_span` | `value: number` | 100–10000 MHz |
| `laser_force_relock` | none | — |
| `tec_power` | `enabled: bool` | — |
| `tec_temperature` | `value: number` | 0–100 °C |
| `external_reference` | `enabled: bool` | — |
| `description` | `target`, `value` | target UL/P1–P7; up to 120 characters, no newlines |
| `optical_power` | `target`, `enabled` | target P1–P7 |
| `downlink_distance` | `target`, `value` | P1–P7, 10–2000 km |
| `downlink_gain` | `target`, `value` | P1–P7, 0/12/24 dB |
| `polarization_control` | `target`, `enabled` | UL/P1–P7 |
| `polarization_speed` | `target`, `value` | UL/P1–P7, `fast`/`slow` |
| `polarization_mode` | `target`, `value` | UL/P1–P7, `continuous`/`triggered` |
| `ping` | `value` | valid IP address or DNS name, up to 253 characters |
| `reboot`, `power_reset`, `factory_default` | none | Administrator |

Targets accept `ul`/`uplink` and `p1`–`p7`/`port1`–`port7`; the canonical form is
sent to the station console.

## TEC and external reference

The controls can turn TEC on or off, set a temperature from 0 to 100 °C, and
allow or disallow the external frequency reference. After changing temperature,
observe the current reading and stabilization state.

## UL and P1–P7

Depending on the installed module type, the available settings are:

- module description;
- optical power enablement;
- downlink distance from 10 to 2000 km;
- additional NC gain of 0, 12, or 24 dB;
- polarization control, controller speed, and mode.

Do not configure an `UNEQUIPPED` slot. The application preserves every physical
position so a result cannot be mistakenly assigned to another port.

## Administrative commands

### Reboot

Restarts station software. The serial connection will drop and the dashboard will
attempt to reconnect approximately every 2 seconds. Do not repeat the restart
until the previous operation has completed or been diagnosed.

### Power reset

Resets station power and may interrupt transfer. Use it only during a maintenance
window. The console may ask for `yes`; after the operation is confirmed in the
dashboard, the application handles that step automatically.

### Factory default

Restores factory station configuration. This can be irreversible with respect to
the current settings. Before using it, record all required system settings and
ensure that a station recommissioning procedure is available.

## Queue and response time

Operator commands enter a queue holding 32 items, while the physical serial
session is owned exclusively by the FTS-LS worker. The usual API wait limit is 20
seconds. Reset commands use longer console read timeouts. A queue-full or timeout
message does not prove that the device did not execute a command; check the
current status and `last_command` before retrying.
