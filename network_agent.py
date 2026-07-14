from __future__ import annotations

import argparse
import http.server
import ipaddress
import json
import os
import shutil
import socket
import socketserver
import subprocess
from dataclasses import dataclass
from typing import Any, Callable


class NetworkAgentError(RuntimeError):
    pass


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
        raise NetworkAgentError(f"Could not run {command[0]}: {exc}") from exc
    if result.returncode != 0:
        raise NetworkAgentError(result.stderr.strip() or result.stdout.strip() or "Unknown command error")
    return result.stdout.strip()


def _prefix(mask: str) -> int:
    value = str(mask).strip().removeprefix("/")
    if value.isdigit() and 0 <= int(value) <= 32:
        return int(value)
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{value}").prefixlen
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError) as exc:
        raise NetworkAgentError("Invalid subnet mask.") from exc


def _nmcli(arguments: list[str], runner: Runner) -> str:
    return _run(["nmcli", *arguments], runner).strip()


def _connection_details(interface: str, runner: Runner) -> dict[str, Any]:
    try:
        connection = _nmcli(["-g", "GENERAL.CONNECTION", "device", "show", interface], runner)
        if not connection or connection == "--":
            return {"connection": "", "mode": "unknown", "dns": []}
        method = _nmcli(["-g", "ipv4.method", "connection", "show", connection], runner)
        dns_text = _nmcli(["-g", "IP4.DNS", "device", "show", interface], runner)
        mode = "dhcp" if method == "auto" else "static" if method == "manual" else method
        return {"connection": connection, "mode": mode, "dns": [v.strip() for v in dns_text.splitlines() if v.strip()]}
    except NetworkAgentError:
        return {"connection": "", "mode": "unknown", "dns": []}


def get_network_state(runner: Runner | None = None) -> dict[str, Any]:
    runner = runner or _default_runner
    if runner is _default_runner and not shutil.which("ip"):
        raise NetworkAgentError("The host ip utility is unavailable.")
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
    selected = next(iter(default_routes), "") or (interfaces[0]["name"] if interfaces else "")
    if not nmcli_available:
        backend, message = "read-only", "NetworkManager is unavailable on the host; settings are read-only."
    else:
        backend, message = "NetworkManager", ""
    return {"hostname": socket.gethostname(), "backend": backend, "supported": nmcli_available, "message": message, "selected_interface": selected, "interfaces": interfaces}


def apply_network_settings(payload: dict[str, Any], runner: Runner | None = None) -> dict[str, Any]:
    runner = runner or _default_runner
    if runner is _default_runner and not shutil.which("nmcli"):
        raise NetworkAgentError("NetworkManager (nmcli) is not installed on the host.")
    current = get_network_state(runner)
    interface = str(payload.get("interface", "")).strip()
    mode = str(payload.get("mode", "")).strip().lower()
    known = {item["name"]: item for item in current["interfaces"]}
    if interface not in known:
        raise NetworkAgentError("The selected host interface does not exist.")
    if mode not in {"dhcp", "static"}:
        raise NetworkAgentError("Select DHCP or static configuration.")
    connection = known[interface].get("connection", "")
    if not connection:
        if _nmcli(["-g", "GENERAL.TYPE", "device", "show", interface], runner) != "ethernet":
            raise NetworkAgentError("Only host Ethernet interfaces can be configured.")
        connection = f"amp-{interface}"
        _run(["nmcli", "connection", "add", "type", "ethernet", "ifname", interface, "con-name", connection], runner)
    command = ["nmcli", "connection", "modify", connection]
    if mode == "dhcp":
        command.extend(["ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", ""])
    else:
        dns_values = payload.get("dns", [])
        if isinstance(dns_values, str):
            dns_values = [v.strip() for v in dns_values.replace(",", " ").split()]
        try:
            address = ipaddress.IPv4Interface(f"{str(payload.get('ip_address', '')).strip()}/{_prefix(str(payload.get('netmask', '')))}")
            gateway = ipaddress.IPv4Address(str(payload.get("gateway", "")).strip())
            dns = [str(ipaddress.IPv4Address(str(v).strip())) for v in dns_values if str(v).strip()]
        except ipaddress.AddressValueError as exc:
            raise NetworkAgentError("The IP address, gateway, or DNS has an invalid format.") from exc
        if gateway not in address.network:
            raise NetworkAgentError("The gateway must be in the same subnet as the IP address.")
        command.extend(["ipv4.method", "manual", "ipv4.addresses", str(address), "ipv4.gateway", str(gateway), "ipv4.dns", ",".join(dns)])
    _run(command, runner)
    _run(["nmcli", "connection", "up", connection], runner)
    return get_network_state(runner)


class _UnixServer(getattr(socketserver, "UnixStreamServer", socketserver.TCPServer)):
    allow_reuse_address = True


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/v1/network":
            self._send(404, {"detail": "Not found."})
            return
        try:
            self._send(200, get_network_state())
        except NetworkAgentError as exc:
            self._send(503, {"detail": str(exc)})

    def do_POST(self) -> None:
        if self.path != "/v1/network":
            self._send(404, {"detail": "Not found."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16384:
                raise NetworkAgentError("Invalid request size.")
            payload = json.loads(self.rfile.read(length))
            self._send(200, apply_network_settings(payload))
        except (NetworkAgentError, json.JSONDecodeError) as exc:
            self._send(400, {"detail": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"network-agent: {format % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/run/amp-dashboard/network-agent.sock")
    args = parser.parse_args()
    os.makedirs(os.path.dirname(args.socket), mode=0o755, exist_ok=True)
    if os.path.exists(args.socket):
        os.unlink(args.socket)
    with _UnixServer(args.socket, Handler) as server:
        os.chmod(args.socket, 0o600)
        server.serve_forever()


if __name__ == "__main__":
    main()
