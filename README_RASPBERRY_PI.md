# Linux dashboard installation

Run this command from the project directory:

```bash
./install_dashboard.sh
```

In an interactive terminal the installer asks whether RADIUS is `local` or
`remote`. Remote mode prompts for the server, UDP port and shared secret (input
is hidden), then requires an explicit `[y/N]` confirmation. Non-interactive
runs keep the existing `.env` configuration.

The installer:

- installs Docker and Docker Compose plugin,
- creates `.env` from `.env.example`,
- generates unique InfluxDB, SNMP and local RADIUS secrets,
- creates a local FreeRADIUS configuration and administrator account,
- configures `systemd-timesyncd` to synchronize the Linux host clock,
- detects `/dev/ttyACM0` or `/dev/ttyUSB0` for the serial device,
- creates the local `data` directory,
- builds and starts the dashboard and InfluxDB containers, plus FreeRADIUS in local mode.

Measurement timestamps come from the NTP-synchronized host clock. The same
UTC timestamp assigned when a serial frame is received is stored in memory,
used by warnings, and written explicitly to InfluxDB.

Application audit events and warnings are sent to the host `rsyslog` service
and stored only in `/var/log/amp-dashboard/amp-dashboard.log`. The installer configures daily
rotation with 30 retained archives. The log is mounted read-only into the app
container solely for the administrator download action.
The dedicated rsyslog template writes one RFC 3339 event timestamp followed by
the dashboard message. It omits the Docker container hostname and does not
duplicate the timestamp inside the audit or warning content.

After installation the dashboard is available at:

```text
http://LINUX_SERVER_IP:8000
```

Initial login:

```text
username: admin
password: printed once by the installer
```

RADIUS is the only password authority. The dashboard stores only the username,
application role and active flag. Passwords are never stored in
`persisted_state.json` and are not managed in the dashboard UI.

The default test setup uses the local FreeRADIUS container:

```text
RADIUS_MODE=local
RADIUS_SERVER=radius
```

To use a central RADIUS server, configure `.env` before rerunning the installer:

```text
RADIUS_MODE=remote
RADIUS_SERVER=192.168.1.50
RADIUS_PORT=1812
RADIUS_SECRET=secret_configured_for_this_dashboard_client
```

In remote mode the installer does not start the local FreeRADIUS container.
Users and passwords must exist on the central server; Administration in the
dashboard only grants those usernames an application role and access.
The central RADIUS administrator must register the Debian host as a RADIUS
client with the same shared secret. The server must be reachable from the host
on UDP/1812.

The generated secrets are stored in `.env` with mode `0600`. InfluxDB's web
port is bound to localhost and is not exposed to the LAN.

Change serial device or service settings in `.env`:

```text
SERIAL_DEVICE=/dev/ttyACM0
SERIAL_PORT=/dev/ttyACM0
SERIAL_BAUDRATE=9600
```

Common maintenance commands:

```bash
sudo docker compose --profile dashboard logs -f app
sudo docker compose --profile dashboard restart app
sudo docker compose --profile dashboard down
sudo docker compose --profile dashboard up -d --build
timedatectl show --property=NTPSynchronized --property=NTP
```

SNMP v2c is exposed on UDP port `1161` by default. Its generated community is
stored in `.env`. Test it locally with:

```bash
docker compose --profile dashboard exec app sh -lc \
  'python snmp_probe.py --host 127.0.0.1 --port "$SNMP_PORT" --community "$SNMP_COMMUNITY"'
```

SNMP v2c does not encrypt traffic; restrict UDP/1161 with the server firewall
to trusted monitoring hosts.
