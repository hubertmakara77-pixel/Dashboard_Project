# The `amp-panel` command

The administration command is intended for package installations. Run operations
that modify configuration or data through `sudo`.

| Command | Operation |
| --- | --- |
| `amp-panel configure` | validates and writes configuration |
| `amp-panel start` | starts the application service |
| `amp-panel stop` | stops the application service |
| `amp-panel restart` | restarts the application service |
| `amp-panel status` | shows full systemd status without a pager |
| `amp-panel logs [-f] [-n N]` | reads the service journal |
| `amp-panel paths` | shows application, configuration, data, log, and runtime paths |
| `amp-panel doctor` | runs nondestructive health checks |
| `amp-panel version` | displays the package version |
| `amp-panel data-dir show` | displays the current data directory |
| `amp-panel data-dir use PATH` | switches to an existing data directory |
| `amp-panel data-dir migrate PATH` | copies managed data and switches configuration |

## Noninteractive configuration

```console
sudo amp-panel configure \
  --non-interactive \
  --device-profile fts-ls \
  --serial-port /dev/serial/by-id/<id> \
  --fts-ls-username appadmin \
  --fts-ls-password '<secret>' \
  --admin-username operator-admin \
  --radius-server 192.0.2.20 \
  --radius-secret '<secret>' \
  --mdns-hostname fts-ls-01
```

Other options include `--port`, `--data-dir`, `--gain-min`, `--gain-max`,
`--radius-port`, `--source`, `--answers-file`, and `--no-start`. Secrets passed as
arguments may be visible in shell history and briefly in process listings. On a
production device, interactive mode or a protected answers file is safer.

Configurator exit code `2` means configuration was not completed. Exit code `1`
from other commands means a validation, service, or health-check failure.
`Ctrl+C` results in code 130.

## Typical diagnostics

```console
sudo amp-panel doctor
sudo amp-panel status
sudo amp-panel logs -n 200
sudo systemctl status amp-panel-network-agent.service --no-pager
```

`amp-panel logs -f` follows the log. Stop it with `Ctrl+C`; doing so does not
affect the service.
