# Dashboard installation on Debian Linux

Installers for the central InfluxDB, remote rsyslog receiver and temporary
FreeRADIUS server are documented in [`server_setup/README.md`](server_setup/README.md).

Run this command from the project directory:

```bash
./install_dashboard.sh
```

In an interactive terminal the installer asks for the external InfluxDB URL,
organization, bucket and API token, followed by the external RADIUS address,
UDP port and shared secret. It then asks whether dashboard events should also
be forwarded to a remote syslog server; if enabled, it asks for the address,
port and TCP/UDP protocol. Secrets are hidden and each remote configuration
requires an explicit `[y/N]` confirmation. Non-interactive runs keep and
validate the existing `.env` configuration.

The installer:

- installs Docker and Docker Compose plugin,
- creates `.env` from `.env.example`,
- assigns a stable device identifier based on the Ethernet MAC address (with
  `/etc/machine-id` as fallback),
- generates a unique SNMP community,
- configures access to external InfluxDB and RADIUS servers,
- configures `systemd-timesyncd` to synchronize the Linux host clock,
- detects `/dev/ttyACM0` or `/dev/ttyUSB0` for the serial device,
- creates the local `data` directory,
- builds and starts only the dashboard container.

InfluxDB and RADIUS are remote-only services. This is required on ARMv7 boards
such as BeagleBone Black, where the official InfluxDB 2 container is not
available. The installer does not install or start either server locally.

Measurement timestamps come from the NTP-synchronized host clock. The same
UTC timestamp assigned when a serial frame is received is stored in memory,
used by warnings, and written explicitly to InfluxDB.

Measurements and setpoints use a durable SQLite outbox at
`/app/data/influx_buffer.db` (host path `data/influx_buffer.db`). Every record is
committed to this file before transmission. A background worker sends records
to InfluxDB in timestamp order and deletes them only after a successful
synchronous write. After an outage or application restart, pending records are
sent automatically with their original timestamps. The default capacity is
250,000 records; once full, the oldest record is discarded before accepting a
new one. Capacity, batch size and retry interval are controlled by:

```text
INFLUX_BUFFER_MAX_RECORDS=250000
INFLUX_BUFFER_BATCH_SIZE=500
INFLUX_RETRY_SECONDS=10
```

The current queue size is exposed as `influx.pending_records` by `/api/status`.
All authenticated users also see the remote database state and buffered record
count in the top status bar. Administrators can open **Service Diagnostics** to
view the InfluxDB endpoint, organization, bucket and SQLite buffer settings,
plus local and remote rsyslog configuration. Server addresses are not exposed
to Operator or Viewer accounts.

The generated identifier has a form such as `beaglebone-a1b2c3d4`. It is
stored as `DEVICE_NAME`, used as the InfluxDB `device` tag, included in every
syslog message and used as the default RADIUS `NAS-Identifier`. It is generated
only when the value is missing or still equals the legacy `optical_amp_1`, so
rerunning the installer does not change an established device identity.

Application audit events and warnings are sent to the host `rsyslog` service
and stored only in `/var/log/amp-dashboard/amp-dashboard.log`. The installer configures daily
rotation with 30 retained archives. The log is mounted read-only into the app
container solely for the administrator download action.
The application also emits `lifecycle` events when it starts, during a graceful
shutdown, and as a periodic heartbeat. The default heartbeat interval is 300
seconds and can be changed with `SYSLOG_HEARTBEAT_SECONDS` (`0` disables it).
Each heartbeat includes the InfluxDB connection state and the number of records
waiting in the local SQLite buffer. A missing heartbeat can be used by central
monitoring to detect a device crash, power loss or network outage.
An administrator can change the heartbeat interval, SQLite record limit and
minimum free disk reserve directly in **Service Diagnostics** without restarting
the application. These values are persisted in `persisted_state.json`. When the
record limit is lowered, excess oldest records are pruned immediately. When the
disk reserve is reached, new records are discarded to protect the operating
system and a syslog warning is emitted.
The dedicated rsyslog template writes one RFC 3339 event timestamp followed by
the dashboard message. It omits the Docker container hostname and does not
duplicate the timestamp inside the audit or warning content.

To retain the local file and forward the same events to a central syslog
server, answer `yes` to the installer prompt. The resulting `.env` settings are:

```text
REMOTE_SYSLOG_ENABLED=true
REMOTE_SYSLOG_HOST=192.168.1.100
REMOTE_SYSLOG_PORT=514
REMOTE_SYSLOG_PROTOCOL=tcp
```

TCP is recommended. The forwarding action uses a persistent rsyslog queue and
retries indefinitely if the central server is temporarily unavailable. Only
events whose program name is `amp-dashboard` are forwarded.

The receiving Debian server must listen on the selected protocol. For TCP,
create `/etc/rsyslog.d/30-amp-dashboard-receiver.conf` containing:

```text
module(load="imtcp")

template(name="ampDashboardRemoteLine" type="string" string="%timereported:::date-rfc3339% %msg:2:$%\n")

if ($programname == "amp-dashboard") then {
    action(
        type="omfile"
        file="/var/log/amp-dashboard/amp-dashboard.log"
        fileOwner="root"
        fileGroup="adm"
        fileCreateMode="0640"
        template="ampDashboardRemoteLine"
    )
    stop
}

input(type="imtcp" port="514")
```

Prepare the destination, validate the configuration and restart the receiver:

```bash
sudo install -d -o root -g adm -m 0750 /var/log/amp-dashboard
sudo touch /var/log/amp-dashboard/amp-dashboard.log
sudo chown root:adm /var/log/amp-dashboard/amp-dashboard.log
sudo chmod 0640 /var/log/amp-dashboard/amp-dashboard.log
sudo rsyslogd -N1
sudo systemctl restart rsyslog
```

Allow TCP/514 only from the Dashboard Debian host in the receiver firewall.

After installation the dashboard is available at:

```text
http://LINUX_SERVER_IP:8000
```

Login:

```text
username: admin
password: password of the `admin` account on the remote RADIUS server
```

RADIUS is the only password authority. The dashboard stores only the username,
application role and active flag. Passwords are never stored in
`persisted_state.json` and are not managed in the dashboard UI.

Configure both remote services in `.env` (or enter these values when prompted):

```text
INFLUX_URL=http://192.168.1.60:8086
INFLUX_TOKEN=token_with_read_and_write_access
INFLUX_ORG=agh
INFLUX_BUCKET=sensors
RADIUS_SERVER=192.168.1.50
RADIUS_PORT=1812
RADIUS_SECRET=secret_configured_for_this_dashboard_client
```

Users and passwords must exist on the central server; Administration in the
dashboard only grants those usernames an application role and access.
The central RADIUS administrator must register the Debian host as a RADIUS
client with the same shared secret. Register the BeagleBone host IP—not the
Docker container IP. RADIUS must be reachable from the dashboard container on
UDP/1812. InfluxDB must be reachable on the port used in `INFLUX_URL`, normally
TCP/8086, and the token needs read/write permission for the configured bucket.

Secrets are stored in `.env` with mode `0600`. Protect access to both central
servers with firewall rules restricted to the BeagleBone host where possible.

Change serial device or service settings in `.env`:

```text
SERIAL_DEVICE=/dev/ttyACM0
SERIAL_PORT=/dev/ttyACM0
SERIAL_BAUDRATE=9600
```

Common maintenance commands:

```bash
sudo docker compose logs -f app
sudo docker compose restart app
sudo docker compose down
sudo docker compose up -d --build
timedatectl show --property=NTPSynchronized --property=NTP
```

SNMP v2c is exposed on UDP port `1161` by default. Its generated community is
stored in `.env`. Test it locally with:

```bash
docker compose exec app sh -lc \
  'python snmp_probe.py --host 127.0.0.1 --port "$SNMP_PORT" --community "$SNMP_COMMUNITY"'
```

SNMP v2c does not encrypt traffic; restrict UDP/1161 with the server firewall
to trusted monitoring hosts.
