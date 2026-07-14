# Network configuration on Debian

The Network Configuration tab reads interfaces with `ip` and manages IPv4 profiles through NetworkManager (`nmcli`). It supports DHCP and static addressing, gateway and DNS configuration.

## Requirements

```bash
sudo apt update
sudo apt install iproute2 network-manager policykit-1
nmcli general status
```

Do not enable NetworkManager remotely before checking whether `ifupdown` or `systemd-networkd` currently owns the interface; taking it over may disconnect SSH.

Run the dashboard as a dedicated service account and grant only `org.freedesktop.NetworkManager.network-control` and `org.freedesktop.NetworkManager.settings.modify.system` through polkit. Avoid running the whole application as root.

Changing the address of the interface used to open the panel can immediately disconnect the browser. Perform the first static-IP change with local access to the device.
