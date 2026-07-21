# Central server setup

These independent installers target minimal Debian-family Linux servers. Run
each script as `root` (use `su -` first on systems without `sudo`). Services may
run on three separate hosts or share one sufficiently sized host.

## InfluxDB

```bash
bash server_setup/install_influx_server.sh
```

Installs Docker, starts the pinned `influxdb:2.9` image, creates persistent
Docker volumes and generates a dashboard token restricted to read/write access
for the selected bucket. Configuration and credentials are stored under
`/opt/amp-influxdb`. Back up both Docker volumes and the secrets directory.
The official InfluxDB image requires an amd64 or arm64 server; do not run this
installer on an ARMv7 BeagleBone Black.

## Remote syslog receiver

```bash
bash server_setup/install_syslog_server.sh
```

Installs native rsyslog, listens on the selected TCP or UDP port and writes only
`amp-dashboard` events to `/var/log/amp-dashboard/amp-dashboard.log`. TCP is
recommended. Daily log rotation keeps 30 compressed archives.

## Temporary RADIUS server

```bash
bash server_setup/install_radius_server.sh
```

Installs native FreeRADIUS and creates one managed dashboard client plus one
test user. Rerunning the script replaces that managed client and user. This
script is intentionally separate so the temporary RADIUS setup can later be
removed without affecting InfluxDB or rsyslog.

## Firewall

Restrict the exposed ports to the dashboard hosts:

- InfluxDB: TCP/8086 (or the selected port),
- syslog: selected TCP/UDP port, normally 514,
- RADIUS: UDP/1812.

Use static addresses or DHCP reservations for the server and BeagleBone hosts.
Every installer prints the exact values required by `install_dashboard.sh`.
