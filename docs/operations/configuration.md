# Host configuration

## Recommended method

Do not manually edit generated files when the same change can be made with:

```console
sudo amp-panel configure
```

`/etc/amp-panel/amp-panel.env` is managed by the configurator, has mode `0600`,
and contains RADIUS, SNMP, and FTS-LS secrets. After a change, the configurator
validates values, writes system files, reloads systemd, and restarts services.

## Minimal amplifier configuration

```dotenv
DEVICE_PROFILE=amplifier
SERIAL_PORT=/dev/serial/by-id/<identifier>
SERIAL_BAUDRATE=9600
GAIN_SET_MIN=<safe-minimum>
GAIN_SET_MAX=<safe-maximum>
INITIAL_ADMIN_USERNAME=<radius-user>
RADIUS_SERVER=<radius-address>
RADIUS_SECRET=<secret>
```

Both gain bounds are required in production. They must be finite numbers and
must satisfy `GAIN_SET_MIN < GAIN_SET_MAX`.

## Minimal FTS-LS configuration

```dotenv
DEVICE_PROFILE=fts-ls
SERIAL_PORT=/dev/serial/by-id/<identifier>
SERIAL_BAUDRATE=115200
FTS_LS_USERNAME=appadmin
FTS_LS_PASSWORD=<station-console-password>
FTS_LS_POLL_SECONDS=10
INITIAL_ADMIN_USERNAME=<radius-user>
RADIUS_SERVER=<radius-address>
RADIUS_SECRET=<secret>
```

The FTS-LS password belongs to the station console and is independent of a
dashboard user's password. The polling interval must be 2–3600 seconds.

## Serial port

Prefer `/dev/serial/by-id/...` because names such as `/dev/ttyACM0` and
`/dev/ttyUSB0` can change after a restart or cable reconnection. The configurator
also accepts `ttyS*` and `ttyO*`. The service user belongs to `dialout`.

After changing the port, run:

```console
sudo amp-panel restart
sudo amp-panel doctor
```

## Data directory

The default path is `/var/lib/amp-panel`. For safety, the tool accepts the
application directory or a directory below `/mnt`, `/media`, or `/srv`; it rejects
`/`, `/etc`, `/usr`, `/var`, and other broad system directories. Change or migrate
the directory only with the commands described in
[backup and data migration](backup.md).

## Persistent dashboard settings

`persisted_state.json` stores the last setpoint, alarm thresholds, local access
list, SNMP settings, and diagnostic settings. It has mode `0600` and is replaced
atomically. Host settings such as profile, RADIUS, and web port remain in
`amp-panel.env`.

The full list of names, defaults, and constraints is in the
[configuration reference](../reference/configuration.md).
