# Linux dashboard installation

Run this command from the project directory:

```bash
./install_dashboard.sh
```

The installer:

- installs Docker and Docker Compose plugin,
- creates `.env` from `.env.example`,
- generates unique administrator, InfluxDB, SNMP and RADIUS secrets,
- creates a local FreeRADIUS configuration and administrator account,
- configures `systemd-timesyncd` to synchronize the Linux host clock,
- detects `/dev/ttyACM0` or `/dev/ttyUSB0` for the serial device,
- creates the local `data` directory,
- builds and starts the dashboard, InfluxDB and FreeRADIUS containers.

Measurement timestamps come from the NTP-synchronized host clock. The same
UTC timestamp assigned when a serial frame is received is stored in memory,
used by warnings, and written explicitly to InfluxDB.

After installation the dashboard is available at:

```text
http://LINUX_SERVER_IP:8000
```

Initial login:

```text
username: admin
password: printed once by the installer
```

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
