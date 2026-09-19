#!/usr/bin/env python3
"""Config-driven SNMP threshold trap daemon.

Zamiast na sztywno wpisanej listy pól w kodzie, czyta definicje trapów z
trap_definitions.json ({"name", "field", "warn_limits_key"}). Dodanie
nowego parametru/urządzenia do monitorowania = nowy wpis w JSON, bez
zmiany tego skryptu.

Wysyła generyczną notyfikację ampThresholdEvent (AMP-PANEL-MIB, OID
.1.3.6.1.4.1.99999.20.2) z varbindami niosącymi NAZWĘ zdarzenia,
zamiast kodować ją w OID - stąd "config-driven", nie "code-driven".

Obsługuje SNMPv3 (authPriv) jeśli ustawione zmienne środowiskowe
SNMPV3_USER/SNMPV3_AUTH_PASS/SNMPV3_PRIV_PASS; w przeciwnym razie
używa v2c (community z persisted_state.json), tak jak poprzednia wersja.
"""
import json
import os
import pathlib
import sqlite3
import subprocess
import time

STATE_FILE = pathlib.Path("/var/lib/amp-panel/persisted_state.json")
DB_FILE = "/var/lib/amp-panel/measurements.db"
DEFINITIONS_FILE = pathlib.Path(
    os.environ.get("TRAP_DEFINITIONS_FILE", "/usr/local/etc/amp-panel/trap_definitions.json")
)
POLL_SECONDS = 10

# AMP-PANEL-MIB: ampThresholdEvent (.20.2) niesie te varbindy (.21.1..21.6)
TRAP_OID = "1.3.6.1.4.1.99999.20.2"
OID_ALARM_NAME = "1.3.6.1.4.1.99999.21.1"
OID_ALARM_STATE = "1.3.6.1.4.1.99999.21.2"
OID_ALARM_VALUE = "1.3.6.1.4.1.99999.21.3"
OID_ALARM_MIN = "1.3.6.1.4.1.99999.21.4"
OID_ALARM_MAX = "1.3.6.1.4.1.99999.21.5"
OID_ALARM_MESSAGE = "1.3.6.1.4.1.99999.21.6"

_active_alerts = set()


def load_trap_definitions():
    try:
        return json.loads(DEFINITIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[error] could not read {DEFINITIONS_FILE}: {exc}", flush=True)
        return []


def load_config():
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    return (raw.get("dashboard_settings", {}) or {}), (raw.get("snmp_settings", {}) or {})


def latest_sample():
    connection = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    row = connection.execute("SELECT * FROM samples ORDER BY id DESC LIMIT 1").fetchone()
    connection.close()
    return dict(row) if row else None


def fmt(value):
    return "unset" if value is None else str(value)


def send_trap(host, port, snmp_settings, name, state, value, minimum, maximum, message):
    varbinds = [
        (OID_ALARM_NAME, "s", name),
        (OID_ALARM_STATE, "s", state),
        (OID_ALARM_VALUE, "s", fmt(value)),
        (OID_ALARM_MIN, "s", fmt(minimum)),
        (OID_ALARM_MAX, "s", fmt(maximum)),
        (OID_ALARM_MESSAGE, "s", message),
    ]

    v3_user = os.environ.get("SNMPV3_USER")
    v3_auth = os.environ.get("SNMPV3_AUTH_PASS")
    v3_priv = os.environ.get("SNMPV3_PRIV_PASS")

    if v3_user and v3_auth and v3_priv:
        command = [
            "snmptrap", "-v3",
            "-u", v3_user, "-l", "authPriv",
            "-a", "SHA", "-A", v3_auth,
            "-x", "AES", "-X", v3_priv,
            f"{host}:{port}", "", TRAP_OID,
        ]
    else:
        community = snmp_settings.get("community", "public")
        command = ["snmptrap", "-v2c", "-c", community, f"{host}:{port}", "", TRAP_OID]

    for oid, type_, value_ in varbinds:
        command.extend([oid, type_, value_])

    subprocess.run(command, check=False, timeout=5)


def check_definition(definition, sample, limits, host, port, snmp_settings):
    field = definition["field"]
    name = definition["name"]
    value = sample.get(field)
    if value is None:
        return

    bounds = limits.get(definition["warn_limits_key"]) or {}
    minimum, maximum = bounds.get("min"), bounds.get("max")
    breached = (minimum is not None and value < minimum) or (maximum is not None and value > maximum)
    was_active = name in _active_alerts

    if breached and not was_active:
        _active_alerts.add(name)
        message = f"{name}: {field}={value:.2f} outside [{fmt(minimum)}, {fmt(maximum)}]"
        send_trap(host, port, snmp_settings, name, "ACTIVE", value, minimum, maximum, message)
        print(f"[trap] ACTIVE {name} {field}={value}", flush=True)
    elif not breached and was_active:
        _active_alerts.discard(name)
        message = f"{name}: {field}={value:.2f} back within [{fmt(minimum)}, {fmt(maximum)}]"
        send_trap(host, port, snmp_settings, name, "CLEAR", value, minimum, maximum, message)
        print(f"[trap] CLEAR {name} {field}={value}", flush=True)


def main():
    definitions = load_trap_definitions()
    if not definitions:
        print(f"[warn] no trap definitions loaded from {DEFINITIONS_FILE} - nothing to monitor", flush=True)

    while True:
        settings, snmp_settings = load_config()
        limits = settings.get("warn_limits", {}) or {}
        host = snmp_settings.get("trap_host", "127.0.0.1")
        port = snmp_settings.get("trap_port", 162)
        sample = latest_sample()

        if sample:
            for definition in definitions:
                check_definition(definition, sample, limits, host, port, snmp_settings)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
