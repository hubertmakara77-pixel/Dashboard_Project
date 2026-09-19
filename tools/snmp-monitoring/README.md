# SNMP: pass_persist config export + threshold trap daemon

An exercise with net-snmp (`snmpd`) that adds two independent monitoring
mechanisms alongside the pysnmp-based agent already built into the app
(`app/services/snmp.py`):

1. **`amp_config_pass_persist.py`** — a `pass_persist` script for `snmpd`.
   Serves the live configuration set in the GUI (gain tolerance, warning
   thresholds `warn_limits`, SNMP community enabled state, last known gain
   set), reading directly from `persisted_state.json`. It does not poll
   anything in a loop — it only reacts to `snmpd` queries (`get`/`getnext`),
   per the pass_persist protocol.

2. **`amp_trap_daemon.py`** — a separate, continuously running process.
   Every 10s it reads the latest sample from `measurements.db` and the
   thresholds from `persisted_state.json`; on a threshold breach it sends
   an `SNMP TRAP` (`ACTIVE`), and once back within range, another TRAP
   (`CLEAR`). The trap is sent to the `trap_host`/`trap_port`/`community`
   configured in the GUI (SNMP Configuration). The trap itself is never
   stored locally — observing it requires an external receiver (e.g.
   Wireshark with filter `udp.port == 162`, or eventually Zabbix/snmptrapd).

## Installing on the device (Debian/BeagleBone)

```bash
sudo apt install -y snmpd snmp
sudo cp amp_config_pass_persist.py amp_trap_daemon.py /usr/local/bin/
sudo chmod +x /usr/local/bin/amp_config_pass_persist.py /usr/local/bin/amp_trap_daemon.py
```

Listen on all interfaces (by default `snmpd` only listens on `127.0.0.1`):

```bash
sudo sed -i 's/^agentaddress.*/agentaddress udp:161/' /etc/snmp/snmpd.conf
```

Community (the same one the app uses for its own agent):

```bash
COMMUNITY=$(sudo grep SNMP_COMMUNITY /etc/amp-panel/amp-panel.env | cut -d= -f2)
echo "rocommunity $COMMUNITY" | sudo tee -a /etc/snmp/snmpd.conf
echo "pass_persist .1.3.6.1.4.1.99999.10 /usr/local/bin/amp_config_pass_persist.py" | sudo tee -a /etc/snmp/snmpd.conf
```

### Permissions — an important detail

`persisted_state.json` and `measurements.db` are owned by the system user
`amp-panel` (`rw-------`/`drwxr-x---`). By default `snmpd` starts as root
but **drops privileges itself** to `Debian-snmp` (`-u Debian-snmp -g Debian-snmp`
in `ExecStart`), so adding it to the group is not enough — `ExecStart` must
be overridden so it does not drop privileges:

```bash
sudo mkdir -p /etc/systemd/system/snmpd.service.d
sudo tee /etc/systemd/system/snmpd.service.d/override.conf > /dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/sbin/snmpd -LOw -I -smux,mteTrigger,mteTriggerConf -f
User=root
Group=root
EOF
sudo systemctl daemon-reload
sudo systemctl restart snmpd
```

### Running the trap daemon as a systemd service

```bash
sudo tee /etc/systemd/system/amp-trap-daemon.service > /dev/null <<'EOF'
[Unit]
Description=Amp Panel threshold trap daemon
After=network.target

[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/amp_trap_daemon.py
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now amp-trap-daemon
```

## Testing

From another machine on the same network (not from the device itself):

```bash
snmpwalk -v2c -c <community> <device_address> .1.3.6.1.4.1.99999.10
```

A threshold change made in the GUI should be visible in the next `snmpwalk`
immediately, with no restart of `snmpd` or the app.

SNMP traffic can be inspected on the device with:

```bash
sudo tcpdump -i any -n udp port 161 or udp port 162
```

## Known limitations of this exercise

- The OIDs (`.1.3.6.1.4.1.99999.10.*`) are private/test values, not
  registered with IANA — for demonstration use, not production.
- Running `snmpd` as `root` (without dropping privileges) simplifies access
  to the app's files but reduces process isolation — acceptable on a lab
  bench, worth revisiting before any production use (e.g. an ACL on the
  data file instead of changing the daemon's user).

# SNMP monitoring toolkit for Amp Panel

A net-snmp (`snmpd`)-based monitoring layer alongside the pysnmp-based agent
already built into the app (`app/services/snmp.py`). Three parts:

1. **`amp_config_pass_persist.py`** - a `pass_persist` script that serves
   the *live* GUI configuration (warning thresholds, gain tolerance, SNMP
   enabled flag, last known gain) over SNMP. It does not poll anything in a
   loop - it only reacts when `snmpd` forwards it a query, so a value
   changed in the GUI is visible on the next SNMP query immediately, no
   restart needed anywhere.
2. **`AMP-PANEL-MIB.mib`** - a private SMIv2 MIB that gives every OID a
   symbolic name, so tools show `ampGainTolerance.0` instead of
   `.1.3.6.1.4.1.99999.10.1.0`.
3. **`amp_trap_daemon_v2.py`** - a standalone daemon that polls the
   measurement database every 10s and sends an SNMP TRAP when a value goes
   outside its configured threshold (`ACTIVE`), and another TRAP when it
   returns within range (`CLEAR`). Which parameters to watch is entirely
   **declared in a JSON file** (`trap_definitions.json`) - adding a new
   parameter or device to monitor never requires touching the Python code.

Everything below assumes the same private enterprise OID already in use:
`.1.3.6.1.4.1.99999` (test/lab value, not registered with IANA).

---

## 1. Installing the agent and the MIB

```bash
sudo apt install -y snmpd snmp
```

Copy the three files onto the device (via `scp` from a machine that has
them - see the repository's `tools/snmp-monitoring/` folder):

```bash
sudo mkdir -p /usr/local/etc/amp-panel
sudo cp trap_definitions.json /usr/local/etc/amp-panel/
sudo cp amp_trap_daemon_v2.py amp_config_pass_persist.py /usr/local/bin/
sudo chmod +x /usr/local/bin/amp_trap_daemon_v2.py /usr/local/bin/amp_config_pass_persist.py
```

**The MIB file, and the three base RFC modules it imports, must live
directly under `/usr/share/snmp/mibs/`** - subdirectories such as
`/usr/share/snmp/mibs/site/` are *not* on net-snmp's default search path on
Debian, even though the tool prints that directory as part of its search
path in some contexts. Always verify with `-Dread_mib` or just check the
"MIB search path" line the tools print - if `.../mibs/site` is not listed,
put the files directly in `.../mibs/`.

```bash
sudo cp AMP-PANEL-MIB.mib /usr/share/snmp/mibs/
```

`AMP-PANEL-MIB.mib` imports `SNMPv2-SMI`, `SNMPv2-TC` and `SNMPv2-CONF`.
If a fresh Debian install does not already have these (check with
`find / -iname "SNMPv2-SMI*" 2>/dev/null`), fetch them from the net-snmp
source tree and drop them in the same directory:

```bash
curl -sL -o SNMPv2-SMI   "https://raw.githubusercontent.com/net-snmp/net-snmp/master/mibs/SNMPv2-SMI.txt"
curl -sL -o SNMPv2-TC    "https://raw.githubusercontent.com/net-snmp/net-snmp/master/mibs/SNMPv2-TC.txt"
curl -sL -o SNMPv2-CONF  "https://raw.githubusercontent.com/net-snmp/net-snmp/master/mibs/SNMPv2-CONF.txt"
sudo cp SNMPv2-SMI SNMPv2-TC SNMPv2-CONF /usr/share/snmp/mibs/
```

Warnings about unrelated modules (`SNMPv2-MIB`, `IF-MIB`, `HOST-RESOURCES-MIB`,
etc.) when running any `snmp*` tool with `-m +AMP-PANEL-MIB` are harmless -
those are standard MIBs for parts of the tree this project does not use
(network interface counters, host resources, ...) and are simply not
installed. They do not affect the `.99999.*` subtree.

---

## 2. Listening address and permissions

By default `snmpd` on Debian only listens on `127.0.0.1`. Make it listen on
all interfaces:

```bash
sudo sed -i 's/^agentaddress.*/agentaddress udp:161/' /etc/snmp/snmpd.conf
```

`persisted_state.json` and `measurements.db` are owned by the `amp-panel`
system user with restrictive permissions. `snmpd` normally drops privileges
to `Debian-snmp` on startup (`-u Debian-snmp -g Debian-snmp` baked into its
`ExecStart`), and simply adding `Debian-snmp` to the `amp-panel` group is
**not** enough, because the file itself is `rw-------` (owner only). The
simplest fix for a lab/demo setup is to stop `snmpd` from dropping
privileges at all, via a systemd drop-in:

```bash
sudo mkdir -p /etc/systemd/system/snmpd.service.d
sudo tee /etc/systemd/system/snmpd.service.d/override.conf > /dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/sbin/snmpd -LOw -I -smux,mteTrigger,mteTriggerConf -f
User=root
Group=root
EOF
sudo systemctl daemon-reload
sudo systemctl restart snmpd
```

(The empty `ExecStart=` line is required first - it clears the inherited
command from the base unit before the new one is set.)

For production hardware, prefer a proper ACL on the data file over running
the agent as root.

---

## 3. Configuration export (community / v2c)

```bash
COMMUNITY=$(sudo grep SNMP_COMMUNITY /etc/amp-panel/amp-panel.env | cut -d= -f2)
echo "rocommunity $COMMUNITY" | sudo tee -a /etc/snmp/snmpd.conf
echo "pass_persist .1.3.6.1.4.1.99999.10 /usr/local/bin/amp_config_pass_persist.py" | sudo tee -a /etc/snmp/snmpd.conf
sudo systemctl restart snmpd
```

## 4. SNMPv3 (authPriv), alongside v2c

```bash
sudo systemctl stop snmpd
echo 'createUser ampv3user SHA "YOUR_AUTH_PASSWORD" AES "YOUR_PRIV_PASSWORD"' | sudo tee -a /var/lib/snmp/snmpd.conf
echo 'rouser ampv3user priv' | sudo tee -a /etc/snmp/snmpd.conf
sudo systemctl start snmpd
```

Both auth and priv passwords must be at least 8 characters. `rouser ... priv`
grants that v3 user read-only access at the `authPriv` security level (both
authenticated and encrypted) to the whole tree by default.

---

## 5. Querying - every combination you'll actually need

Run these from a **different machine** on the network, not from the device
itself (querying `127.0.0.1` only proves the agent works locally, not that
it's reachable).

### By raw OID, SNMPv2c

```bash
snmpwalk -v2c -c <community> <device_ip> .1.3.6.1.4.1.99999.10
snmpget  -v2c -c <community> <device_ip> .1.3.6.1.4.1.99999.10.1.0
```

### By symbolic name, SNMPv2c (requires `-m +AMP-PANEL-MIB`)

```bash
snmpwalk -v2c -c <community> -m +AMP-PANEL-MIB <device_ip> AMP-PANEL-MIB::ampConfig
snmpget  -v2c -c <community> -m +AMP-PANEL-MIB <device_ip> AMP-PANEL-MIB::ampGainTolerance.0
```

### By raw OID, SNMPv3 (authPriv)

```bash
snmpwalk -v3 -u ampv3user -l authPriv -a SHA -A "YOUR_AUTH_PASSWORD" -x AES -X "YOUR_PRIV_PASSWORD" \
    <device_ip> .1.3.6.1.4.1.99999.10
```

### By symbolic name, SNMPv3 (authPriv) - the "full" command

```bash
snmpwalk -v3 -u ampv3user -l authPriv -a SHA -A "YOUR_AUTH_PASSWORD" -x AES -X "YOUR_PRIV_PASSWORD" \
    -m +AMP-PANEL-MIB <device_ip> AMP-PANEL-MIB::ampConfig

snmpget -v3 -u ampv3user -l authPriv -a SHA -A "YOUR_AUTH_PASSWORD" -x AES -X "YOUR_PRIV_PASSWORD" \
    -m +AMP-PANEL-MIB <device_ip> AMP-PANEL-MIB::ampLastGainSet.0
```

Flag reference (net-snmp CLI tools, same flags across `snmpwalk`/`snmpget`/`snmptrap`):

| Flag | Meaning |
|---|---|
| `-v2c` / `-v3` | protocol version |
| `-c <community>` | v2c community string |
| `-u <user>` | v3 username |
| `-l authPriv` | v3 security level: authenticated + encrypted |
| `-a SHA -A <password>` | v3 authentication algorithm and password |
| `-x AES -X <password>` | v3 privacy (encryption) algorithm and password |
| `-m +AMP-PANEL-MIB` | load this MIB in addition to the defaults, to resolve names |
| `-On` | print OIDs as raw dotted numbers (useful when debugging) |
| `-Of` | print OIDs as the full symbolic path |
| `-Td` | print a MIB node's full textual definition (SYNTAX, DESCRIPTION, ...) |

### Translating names without touching the network (`snmptranslate`)

Useful for checking the MIB itself loads correctly before blaming the
network:

```bash
snmptranslate -m +AMP-PANEL-MIB -On AMP-PANEL-MIB::ampAlarmName   # name -> OID
snmptranslate -m +AMP-PANEL-MIB -Of .1.3.6.1.4.1.99999.20.2       # OID -> name
snmptranslate -m +AMP-PANEL-MIB -Td AMP-PANEL-MIB::ampGainTolerance  # full definition
```

### Watching raw SNMP traffic

```bash
sudo tcpdump -i any -n udp port 161 or udp port 162
```

---

## 6. OID / name reference

### Configuration objects (`ampConfig`, `.99999.10.*`) - read-only, live

| Name | OID | Meaning |
|---|---|---|
| `ampGainTolerance` | `.10.1` | Allowed gain deviation (dB) |
| `ampPiaWarnMin` / `ampPiaWarnMax` | `.10.2` / `.10.3` | Warning thresholds, input power port A (dBm) |
| `ampPoaWarnMin` / `ampPoaWarnMax` | `.10.4` / `.10.5` | Warning thresholds, output power port A (dBm) |
| `ampPibWarnMin` / `ampPibWarnMax` | `.10.6` / `.10.7` | Warning thresholds, input power port B (dBm) |
| `ampPobWarnMin` / `ampPobWarnMax` | `.10.8` / `.10.9` | Warning thresholds, output power port B (dBm) |
| `ampTemperatureWarnMin` / `ampTemperatureWarnMax` | `.10.10` / `.10.11` | Warning thresholds, temperature (deg C) |
| `ampSnmpEnabled` | `.10.12` | Whether the built-in SNMP agent is enabled in the GUI |
| `ampLastGainSet` | `.10.13` | Last gain setpoint requested |

A value shows as the string `"unset"` when the GUI has not configured that
threshold (`null` in `persisted_state.json`).

### Alarm/trap varbinds (`ampAlarmObjects`, `.99999.21.*`)

| Name | OID | Meaning |
|---|---|---|
| `ampAlarmName` | `.21.1` | Name of the alarm definition that fired (from `trap_definitions.json`) |
| `ampAlarmState` | `.21.2` | `ACTIVE` or `CLEAR` |
| `ampAlarmValue` | `.21.3` | Measured value |
| `ampAlarmThresholdMin` / `ampAlarmThresholdMax` | `.21.4` / `.21.5` | Configured threshold(s) |
| `ampAlarmMessage` | `.21.6` | Free-text summary |

### Notifications (`ampNotifications`, `.99999.20.*`)

| Name | OID | Notes |
|---|---|---|
| `ampThresholdEventLegacy` | `.20.1` | Deprecated single-varbind trap (kept for backward compatibility) |
| `ampThresholdEvent` | `.20.2` | Current, generic trap - carries all six alarm varbinds above |

---

## 7. Config-driven trap daemon

`amp_trap_daemon_v2.py` reads `/usr/local/etc/amp-panel/trap_definitions.json`
on startup and polls the `samples` table in `measurements.db` every 10
seconds. For every entry it compares `sample[field]` against
`persisted_state.json -> dashboard_settings -> warn_limits[warn_limits_key]`.
On a breach it sends `ampThresholdEvent` with `ampAlarmState = ACTIVE`; once
the value is back within range it sends the same notification with
`ampAlarmState = CLEAR`. Each alarm name is tracked independently, so
several can be active at once.

### Definition file format

```json
[
    {"name": "PiaOutOfRange", "field": "PiA", "warn_limits_key": "PiA", "unit": "dBm"}
]
```

- `name` - free-form identifier, becomes the `ampAlarmName` varbind value.
  This is what an operator sees; no OID needs to be invented for it.
- `field` - column name in the `samples` SQLite table to read.
- `warn_limits_key` - key under `dashboard_settings.warn_limits` in
  `persisted_state.json` to compare against (usually the same as `field`,
  but does not have to be - see the example below).
- `unit` - informational only, not currently used by the daemon logic.

### Adding a new monitored parameter or device - no code change

Append an entry to the JSON file and restart the daemon:

```bash
sudo python3 -c "
import json
path = '/usr/local/etc/amp-panel/trap_definitions.json'
data = json.load(open(path))
data.append({'name': 'MyNewAlarm', 'field': 'temperature', 'warn_limits_key': 'temperature', 'unit': 'C'})
json.dump(data, open(path, 'w'), indent=2)
"
sudo systemctl restart amp-trap-daemon
```

`amp_trap_daemon_v2.py` itself never needs editing for this - it is a
static list of six varbind OIDs (defined once, in the MIB) plus whatever
the JSON file currently contains.

### Running it as a service

```bash
sudo tee /etc/systemd/system/amp-trap-daemon.service > /dev/null <<'EOF'
[Unit]
Description=Amp Panel config-driven threshold trap daemon
After=network.target

[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/amp_trap_daemon_v2.py
Environment=SNMPV3_USER=ampv3user
Environment=SNMPV3_AUTH_PASS=YOUR_AUTH_PASSWORD
Environment=SNMPV3_PRIV_PASS=YOUR_PRIV_PASSWORD
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now amp-trap-daemon
sudo journalctl -u amp-trap-daemon -f
```

If `SNMPV3_USER`/`SNMPV3_AUTH_PASS`/`SNMPV3_PRIV_PASS` are all set, traps go
out via SNMPv3 authPriv. If any is missing, the daemon falls back to SNMPv2c
using the `community` from `persisted_state.json -> snmp_settings`.

Trap destination (`trap_host` / `trap_port`) is read from the same GUI
setting (SNMP Configuration tab) on every poll cycle - changing it in the
GUI takes effect within 10 seconds, no restart needed.

### Observing a trap

A trap is fire-and-forget (UDP, unacknowledged) - it must be caught by
something external at the moment it is sent:

```bash
sudo tcpdump -i any -n udp port 162
```

or Wireshark on the receiving machine, filter `udp.port == 162`. With
SNMPv3 authPriv, the payload is encrypted, so a plain packet capture will
show that a trap was sent but not its contents - use a matching `snmptrapd`
configured with the same v3 credentials to actually decode it.

---

## 8. Known limitations

- OIDs under `.1.3.6.1.4.1.99999.*` are private/test values, not registered
  with IANA - fine for a lab/demo device, not for production without a real
  Private Enterprise Number.
- `snmpd` running as root (privilege-drop disabled) simplifies file access
  for this exercise but reduces process isolation; revisit with a proper
  file ACL before any production use.
- `unit` in `trap_definitions.json` is documentation only; it is not
  validated or converted by the daemon.
