from __future__ import annotations

import ipaddress
import json
import shutil
import socket
import subprocess
from dataclasses import dataclass
from typing import Any, Callable


class NetworkError(RuntimeError):
    """A network configuration error safe to show in the dashboard."""


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str]], CommandResult]


def _default_runner(command: list[str]) -> CommandResult:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _run(command: list[str], runner: Runner) -> str:
    try:
        result = runner(command)
    except (OSError, subprocess.SubprocessError) as exc:
        raise NetworkError(f"Could not run {command[0]}: {exc}") from exc
    if result.returncode != 0:
        raise NetworkError(result.stderr.strip() or result.stdout.strip() or "Unknown command error")
    return result.stdout.strip()


def _nmcli_value(arguments: list[str], runner: Runner) -> str:
    return _run(["nmcli", *arguments], runner).strip()


def _network_prefix(mask: str) -> int:
    value = str(mask).strip().removeprefix("/")
    if value.isdigit():
        prefix = int(value)
        if 0 <= prefix <= 32:
            return prefix
        raise NetworkError("The subnet prefix must be between 0 and 32.")
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{value}").prefixlen
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError) as exc:
        raise NetworkError("Invalid subnet mask.") from exc


def _connection_details(interface: str, runner: Runner) -> dict[str, Any]:
    try:
        connection = _nmcli_value(["-g", "GENERAL.CONNECTION", "device", "show", interface], runner)
        if not connection or connection == "--":
            return {"connection": "", "mode": "unknown", "dns": []}
        method = _nmcli_value(["-g", "ipv4.method", "connection", "show", connection], runner)
        dns_text = _nmcli_value(["-g", "IP4.DNS", "device", "show", interface], runner)
        mode = "dhcp" if method == "auto" else "static" if method == "manual" else method
        return {"connection": connection, "mode": mode, "dns": [line.strip() for line in dns_text.splitlines() if line.strip()]}
    except NetworkError:
        return {"connection": "", "mode": "unknown", "dns": []}


def get_network_state(runner: Runner | None = None) -> dict[str, Any]:
    runner = runner or _default_runner
    if runner is _default_runner and not shutil.which("ip"):
        return {"hostname": socket.gethostname(), "backend": "unavailable", "supported": False, "message": "The ip utility is unavailable. Network management is supported on Debian.", "selected_interface": "", "interfaces": []}

    addresses = json.loads(_run(["ip", "-j", "address", "show"], runner) or "[]")
    routes = json.loads(_run(["ip", "-j", "route", "show", "default"], runner) or "[]")
    default_routes = {route.get("dev"): route for route in routes if route.get("dev")}
    nmcli_available = runner is not _default_runner or shutil.which("nmcli") is not None
    interfaces = []
    for item in addresses:
        name = str(item.get("ifname", ""))
        if not name or name == "lo":
            continue
        ipv4 = next((entry for entry in item.get("addr_info", []) if entry.get("family") == "inet"), None)
        prefix = int(ipv4.get("prefixlen", 0)) if ipv4 else None
        details = _connection_details(name, runner) if nmcli_available else {"connection": "", "mode": "unknown", "dns": []}
        interfaces.append({"name": name, "mac": item.get("address", ""), "state": str(item.get("operstate", "unknown")).lower(), "ip_address": ipv4.get("local", "") if ipv4 else "", "prefix": prefix, "netmask": str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask) if prefix is not None else "", "gateway": default_routes.get(name, {}).get("gateway", ""), **details})

    selected = next((name for name in default_routes if name != "lo"), "")
    if not selected and interfaces:
        selected = next((item["name"] for item in interfaces if item["state"] == "up"), interfaces[0]["name"])
    return {"hostname": socket.gethostname(), "backend": "NetworkManager" if nmcli_available else "read-only", "supported": nmcli_available, "message": "" if nmcli_available else "nmcli is unavailable; settings are read-only.", "selected_interface": selected, "interfaces": interfaces}


def apply_network_settings(payload: dict[str, Any], runner: Runner | None = None) -> dict[str, Any]:
    runner = runner or _default_runner
    if runner is _default_runner and not shutil.which("nmcli"):
        raise NetworkError("NetworkManager (nmcli) is not installed.")
    interface = str(payload.get("interface", "")).strip()
    mode = str(payload.get("mode", "")).strip().lower()
    current = get_network_state(runner)
    known = {item["name"]: item for item in current["interfaces"]}
    if interface not in known:
        raise NetworkError("The selected network interface does not exist.")
    if mode not in {"dhcp", "static"}:
        raise NetworkError("Select DHCP or static configuration.")

    connection = known[interface].get("connection", "")
    if not connection:
        device_type = _nmcli_value(["-g", "GENERAL.TYPE", "device", "show", interface], runner)
        if device_type != "ethernet":
            raise NetworkError("Create a NetworkManager connection for this interface first.")
        connection = f"amp-{interface}"
        _run(["nmcli", "connection", "add", "type", "ethernet", "ifname", interface, "con-name", connection], runner)

    command = ["nmcli", "connection", "modify", connection]
    if mode == "dhcp":
        command.extend(["ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", ""])
    else:
        dns_values = payload.get("dns", [])
        if isinstance(dns_values, str):
            dns_values = [part.strip() for part in dns_values.replace(",", " ").split()]
        prefix = _network_prefix(str(payload.get("netmask", "")))
        try:
            address = ipaddress.IPv4Interface(f"{str(payload.get('ip_address', '')).strip()}/{prefix}")
            gateway = ipaddress.IPv4Address(str(payload.get("gateway", "")).strip())
            dns = [str(ipaddress.IPv4Address(str(value).strip())) for value in dns_values if str(value).strip()]
        except ipaddress.AddressValueError as exc:
            raise NetworkError("The IP address, gateway, or DNS has an invalid format.") from exc
        if gateway not in address.network:
            raise NetworkError("The gateway must be in the same subnet as the IP address.")
        command.extend(["ipv4.method", "manual", "ipv4.addresses", str(address), "ipv4.gateway", str(gateway), "ipv4.dns", ",".join(dns)])
    _run(command, runner)
    _run(["nmcli", "connection", "up", connection], runner)
    return get_network_state(runner)
