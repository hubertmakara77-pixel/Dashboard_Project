# Host network configuration

The dashboard container never executes `ip` or `nmcli` and does not receive
privileged access. It communicates over the root-owned Unix socket
`/run/amp-dashboard/network-agent.sock` with `amp-network-agent.service`, a
small systemd service installed on the Linux host.

The agent validates interface names, IPv4 addresses, subnet, gateway and DNS,
then invokes NetworkManager without a shell. Only Administrators may submit a
change through the dashboard; all authenticated roles may read the state.

## Debian / Raspberry Pi OS host

The host must use NetworkManager for the interface that should be managed:

```bash
sudo apt update
sudo apt install iproute2 network-manager
nmcli general status
nmcli device status
```

Do not switch an existing remote server from `ifupdown`, Netplan or
`systemd-networkd` to NetworkManager without local console access. Taking over
the active interface may immediately disconnect SSH and the dashboard.

Run `install_raspberry_pi.sh` after NetworkManager is ready. The installer
installs and enables both `amp-network-agent.service` and
`amp-dashboard.service`.

## Diagnostics

```bash
sudo systemctl status amp-network-agent.service
sudo journalctl -u amp-network-agent.service -n 100
ls -l /run/amp-dashboard/network-agent.sock
docker compose --profile dashboard exec app python -c \
  'import network_service; print(network_service.get_network_state())'
```
