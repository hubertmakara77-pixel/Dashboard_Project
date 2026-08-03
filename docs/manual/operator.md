# Operator manual

## Navigation

The dashboard groups functions into three areas:

- **Device** — the live view and, for Operators and Administrators, settings;
- **Monitor** — overview, statistics, alarms, and history;
- **Admin** — functions available only to Administrators.

A Viewer can read data and export history. An Operator can additionally change
device setpoints and alarm settings, and acknowledge alarms.

## Live View — amplifier

The view shows input and output power for channels A/B (`PiA`, `PoA`, `PiB`,
`PoB`), actual gain, setpoint, deviation, and temperature. **Gain delta** is the
difference between the set and actual gain.

### Changing the gain setpoint

1. Check the safe range shown next to the setpoint field.
2. Enter and submit the new value.
3. Wait for the device response confirmation.
4. Verify that the setpoint and delta update in subsequent measurements.

The backend rejects `NaN`, infinity, and values outside `GAIN_SET_MIN` and
`GAIN_SET_MAX`. A missing serial connection returns a service error and is not
treated as a successful change.

## Live View — FTS-LS

The view is divided into the internal laser, synthesizer, TEC, UL module, and
physical slots P1–P7. An empty slot stays in its physical position and is marked
`UNEQUIPPED`; numbering is never compressed. Detailed controls are described in
[FTS-LS station](fts-ls.md).

## Amplifier alarm settings

An Operator can configure:

- allowed gain deviation (`gain_tolerance`);
- lower and upper thresholds for PiA, PoA, PiB, PoB, and temperature.

An empty threshold disables that boundary. A lower limit must be less than its
upper limit. A gain-deviation alarm opens when
`abs(gain_delta) > gain_tolerance`.

## Alarms

The list distinguishes active alarms from historical events. Available history
ranges are session, 1 hour, 24 hours, 7 days, 30 days, and custom. Results can be
filtered by field and `open`/`cleared` status.

**Acknowledge all** records that the operator has seen the active alarms. It does
not close an alarm or change a threshold. When the cause disappears, the
application records a separate `CLEARED` event. Alarm openings are also sent as
SNMP traps when SNMP is enabled.

### FTS-LS alarms

The dashboard automatically reports, among other conditions:

- a module in the `UNLOCKED` state;
- LF noise above 100;
- jitter above 50;
- an optical-power indication of `LOW` or `HIGH` (expected indication:
  -65…-33 dBm);
- unavailable or failed power supply A/B.

These thresholds are currently fixed by the FTS-LS profile logic and cannot be
edited on the settings screen.

## History, statistics, and export

Amplifier ranges are 5 minutes, 1 hour, 24 hours, 7 days, 30 days, and all
history. Chart data may be reduced to the configured maximum number of points,
but CSV export streams raw records. The file uses `;` as its separator and starts
with `sep=;` for compatibility with spreadsheet applications using semicolon CSV.

FTS-LS history stores complete station snapshots. Export flattens laser, TEC,
synthesizer, UL, and P1–P7 fields into CSV columns. A single request can return at
most 10,000 snapshots.

## Setpoint-change practice

Record the starting value, make one change at a time, and observe at least one
complete polling cycle. For FTS-LS, the cycle is controlled by
`FTS_LS_POLL_SECONDS` and defaults to 10 seconds.
