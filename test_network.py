import json
import unittest

from network_agent import CommandResult, NetworkAgentError, apply_network_settings, get_network_state

ADDRESSES = [{"ifname": "lo", "operstate": "UNKNOWN", "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}]}, {"ifname": "eth0", "address": "dc:a6:32:00:00:01", "operstate": "UP", "addr_info": [{"family": "inet", "local": "192.168.10.20", "prefixlen": 24}]}]
ROUTES = [{"dst": "default", "gateway": "192.168.10.1", "dev": "eth0"}]


class FakeRunner:
    def __init__(self, method="auto"):
        self.method, self.commands = method, []

    def __call__(self, command):
        self.commands.append(command)
        if command == ["ip", "-j", "address", "show"]: return CommandResult(0, json.dumps(ADDRESSES), "")
        if command == ["ip", "-j", "route", "show", "default"]: return CommandResult(0, json.dumps(ROUTES), "")
        if command[:4] == ["nmcli", "-g", "GENERAL.CONNECTION", "device"]: return CommandResult(0, "Wired connection 1\n", "")
        if command[:4] == ["nmcli", "-g", "ipv4.method", "connection"]: return CommandResult(0, f"{self.method}\n", "")
        if command[:4] == ["nmcli", "-g", "IP4.DNS", "device"]: return CommandResult(0, "1.1.1.1\n8.8.8.8\n", "")
        if command[:3] in (["nmcli", "connection", "modify"], ["nmcli", "connection", "up"]): return CommandResult(0, "", "")
        return CommandResult(1, "", f"Unexpected command: {command}")


class NetworkAgentTests(unittest.TestCase):
    def test_reads_host_configuration(self):
        current = get_network_state(FakeRunner())
        self.assertTrue(current["supported"])
        self.assertEqual(current["selected_interface"], "eth0")
        self.assertEqual(current["interfaces"][0]["netmask"], "255.255.255.0")

    def test_applies_static_configuration_without_shell(self):
        runner = FakeRunner("manual")
        apply_network_settings({"interface": "eth0", "mode": "static", "ip_address": "192.168.10.50", "netmask": "24", "gateway": "192.168.10.1", "dns": "1.1.1.1, 8.8.8.8"}, runner)
        modify = next(command for command in runner.commands if command[:3] == ["nmcli", "connection", "modify"])
        self.assertIn("192.168.10.50/24", modify)

    def test_rejects_gateway_outside_subnet(self):
        with self.assertRaisesRegex(NetworkAgentError, "same subnet"):
            apply_network_settings({"interface": "eth0", "mode": "static", "ip_address": "192.168.10.50", "netmask": "24", "gateway": "10.0.0.1", "dns": ""}, FakeRunner())


if __name__ == "__main__":
    unittest.main()
