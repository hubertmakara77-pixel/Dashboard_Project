import json
import unittest
from unittest import mock

from tools.network_agent import (
    CommandResult,
    NetworkAgentError,
    apply_network_settings,
    confirm_network_settings,
    get_network_state,
)

ADDRESSES = [
    {
        "ifname": "lo",
        "operstate": "UNKNOWN",
        "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}],
    },
    {
        "ifname": "eth0",
        "address": "dc:a6:32:00:00:01",
        "operstate": "UP",
        "addr_info": [{"family": "inet", "local": "192.168.10.20", "prefixlen": 24}],
    },
]
ROUTES = [{"dst": "default", "gateway": "192.168.10.1", "dev": "eth0"}]


class FakeRunner:
    def __init__(self, method="auto"):
        self.method, self.commands = method, []

    def __call__(self, command):
        self.commands.append(command)
        if command == ["ip", "-j", "address", "show"]:
            return CommandResult(0, json.dumps(ADDRESSES), "")
        if command == ["ip", "-j", "route", "show", "default"]:
            return CommandResult(0, json.dumps(ROUTES), "")
        if command == ["ip", "-j", "route", "get", "192.168.10.40"]:
            return CommandResult(0, json.dumps([{"dst": "192.168.10.40", "dev": "eth0"}]), "")
        if command == ["ip", "-j", "route", "get", "10.20.30.40"]:
            return CommandResult(0, json.dumps([{"dst": "10.20.30.40", "dev": "eth1"}]), "")
        if command == ["ip", "-j", "route", "get", "172.18.0.1"]:
            return CommandResult(
                0, json.dumps([{"type": "local", "dst": "172.18.0.1", "dev": "lo"}]), ""
            )
        if command[:4] == ["nmcli", "-g", "GENERAL.CONNECTION", "device"]:
            return CommandResult(0, "Wired connection 1\n", "")
        if command[:4] == ["nmcli", "-g", "ipv4.method", "connection"]:
            return CommandResult(0, f"{self.method}\n", "")
        if command[:4] == ["nmcli", "-g", "IP4.DNS", "device"]:
            return CommandResult(0, "1.1.1.1\n8.8.8.8\n", "")
        if command[:3] in (["nmcli", "connection", "modify"], ["nmcli", "connection", "up"]):
            return CommandResult(0, "", "")
        if command[:6] == [
            "busctl",
            "call",
            "org.freedesktop.NetworkManager",
            "/org/freedesktop/NetworkManager",
            "org.freedesktop.NetworkManager",
            "GetDeviceByIpIface",
        ]:
            return CommandResult(0, 'o "/org/freedesktop/NetworkManager/Devices/2"\n', "")
        if command[:6] == [
            "busctl",
            "call",
            "org.freedesktop.NetworkManager",
            "/org/freedesktop/NetworkManager",
            "org.freedesktop.NetworkManager",
            "CheckpointCreate",
        ]:
            return CommandResult(0, 'o "/org/freedesktop/NetworkManager/Checkpoint/1"\n', "")
        if command[:6] in (
            [
                "busctl",
                "call",
                "org.freedesktop.NetworkManager",
                "/org/freedesktop/NetworkManager",
                "org.freedesktop.NetworkManager",
                "CheckpointDestroy",
            ],
            [
                "busctl",
                "call",
                "org.freedesktop.NetworkManager",
                "/org/freedesktop/NetworkManager",
                "org.freedesktop.NetworkManager",
                "CheckpointRollback",
            ],
        ):
            return CommandResult(0, "", "")
        return CommandResult(1, "", f"Unexpected command: {command}")


class NetworkAgentTests(unittest.TestCase):
    def test_reads_host_configuration(self):
        with mock.patch(
            "tools.network_agent.socket.gethostname",
            return_value="amp-panel-a1b2c3d4",
        ):
            current = get_network_state(FakeRunner())
        self.assertTrue(current["supported"])
        self.assertEqual(current["selected_interface"], "eth0")
        self.assertEqual(current["interfaces"][0]["netmask"], "255.255.255.0")
        self.assertEqual(
            current["mdns_hostname"],
            "amp-panel-a1b2c3d4.local",
        )

    def test_applies_static_configuration_without_shell(self):
        runner = FakeRunner("manual")
        result = apply_network_settings(
            {
                "interface": "eth0",
                "mode": "static",
                "ip_address": "192.168.10.50",
                "netmask": "24",
                "gateway": "192.168.10.1",
                "dns": "1.1.1.1, 8.8.8.8",
                "_requester_ip": "192.168.10.40",
            },
            runner,
        )
        modify = next(
            command
            for command in runner.commands
            if command[:3] == ["nmcli", "connection", "modify"]
        )
        self.assertIn("192.168.10.50/24", modify)
        self.assertEqual(result["confirmation"]["status"], "pending")
        checkpoint_index = next(
            index
            for index, command in enumerate(runner.commands)
            if len(command) > 5 and command[5] == "CheckpointCreate"
        )
        modify_index = runner.commands.index(modify)
        self.assertLess(checkpoint_index, modify_index)
        confirmed = confirm_network_settings(
            result["confirmation"]["token"], runner, "192.168.10.40"
        )
        self.assertEqual(confirmed["confirmation"]["status"], "confirmed")
        self.assertTrue(
            any(
                len(command) > 5 and command[5] == "CheckpointDestroy"
                for command in runner.commands
            )
        )
        self.assertEqual(runner.commands[-1][5], "CheckpointDestroy")

    def test_rejects_gateway_outside_subnet(self):
        with self.assertRaisesRegex(NetworkAgentError, "same subnet"):
            apply_network_settings(
                {
                    "interface": "eth0",
                    "mode": "static",
                    "ip_address": "192.168.10.50",
                    "netmask": "24",
                    "gateway": "10.0.0.1",
                    "dns": "",
                    "_requester_ip": "192.168.10.40",
                },
                FakeRunner(),
            )

    def test_rolls_back_when_activation_fails(self):
        class FailingRunner(FakeRunner):
            def __call__(self, command):
                if command[:3] == ["nmcli", "connection", "up"]:
                    self.commands.append(command)
                    return CommandResult(1, "", "activation failed")
                return super().__call__(command)

        runner = FailingRunner()
        with self.assertRaisesRegex(NetworkAgentError, "activation failed"):
            apply_network_settings(
                {"interface": "eth0", "mode": "dhcp", "_requester_ip": "192.168.10.40"},
                runner,
            )
        self.assertTrue(
            any(
                len(command) > 5 and command[5] == "CheckpointRollback"
                for command in runner.commands
            )
        )

    def test_rejects_interface_not_used_by_dashboard_client(self):
        with self.assertRaisesRegex(NetworkAgentError, "uses interface eth1"):
            apply_network_settings(
                {
                    "interface": "eth0",
                    "mode": "dhcp",
                    "_requester_ip": "10.20.30.40",
                },
                FakeRunner(),
            )

    def test_rejects_confirmation_through_a_different_interface(self):
        runner = FakeRunner()
        result = apply_network_settings(
            {
                "interface": "eth0",
                "mode": "dhcp",
                "_requester_ip": "192.168.10.40",
            },
            runner,
        )
        with self.assertRaisesRegex(NetworkAgentError, "did not arrive through"):
            confirm_network_settings(
                result["confirmation"]["token"],
                runner,
                "10.20.30.40",
            )
        confirm_network_settings(
            result["confirmation"]["token"],
            runner,
            "192.168.10.40",
        )


if __name__ == "__main__":
    unittest.main()
