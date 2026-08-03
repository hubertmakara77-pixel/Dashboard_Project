# Installation and upgrade

## Target environment

The production deployment method is a Debian package managed by systemd. The
package installs the application in `/usr/lib/amp-panel`, configuration in
`/etc/amp-panel`, data in `/var/lib/amp-panel`, logs in `/var/log/amp-panel`, and
runtime files in `/run/amp-panel`. The application runs as the unprivileged
`amp-panel` user. A separate root service performs only controlled NetworkManager
operations.

## Package installation

Copy the `.deb` file for the target architecture to the device, then run:

```console
sudo apt install ./amp-panel_<version>_<architecture>.deb
sudo amp-panel configure
```

The configurator asks for the device profile, web port, serial port, data
directory, initial user, RADIUS settings, and mDNS name. The amplifier profile
requires safe setpoint bounds. FTS-LS requires the station console username and
password.

After successful configuration, services are enabled and restarted. The
configurator prints an address such as `http://<mdns>.local:<port>`.

## Installation verification

```console
sudo amp-panel doctor
sudo amp-panel status
sudo amp-panel logs -n 100
sudo amp-panel paths
```

`doctor` checks configuration, the data directory, SQLite integrity, serial-port
presence, and service state. A missing serial port is a warning; an invalid
database or stopped service is a failure and results in a nonzero exit code.

## Upgrade

Before upgrading, create a copy according to the [backup procedure](backup.md).
Then run:

```console
sudo apt install ./amp-panel_<new-version>_<architecture>.deb
sudo amp-panel configure
sudo amp-panel doctor
```

The configurator reads the current configuration when it is present. SQLite
schema migrations run at startup. Do not copy only `measurements.db` while the
service is running without accounting for WAL/SHM files; follow the backup
procedure.

Configuration is written atomically with mode `0600`.

## Building the package

Build on Linux for the target architecture:

```console
sudo apt install build-essential debhelper git
./packaging/prepare_vendor.sh
./packaging/build_deb.sh
```

`packaging/VERSION` must match `debian/changelog`. The script builds from files
committed to Git, so uncommitted changes and local drafts are excluded from the
artifact. The resulting package is copied to the repository's parent directory.
