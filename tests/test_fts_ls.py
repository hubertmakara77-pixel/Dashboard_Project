import unittest

from app.core import state
from app.protocols import fts_ls as fts_protocol


class FtsLsTests(unittest.TestCase):
    def test_status_contract_does_not_invent_station_power_supplies(self):
        self.assertNotIn("power", state.empty_fts_ls_status())
        self.assertNotIn("power", fts_protocol.DETAIL_SECTIONS)

    def test_documented_commands_are_built_with_validation(self):
        self.assertEqual(
            fts_protocol.build_command("laser_central_frequency", {"value": 194397.7}),
            "set laser central frequency 194397.7",
        )
        self.assertEqual(
            fts_protocol.build_command("laser_central_frequency", {"value": 194400}),
            "set laser central frequency 194400",
        )
        self.assertEqual(
            fts_protocol.build_command("downlink_distance", {"target": "P2", "value": 500}),
            "set port2 downlink distance 500",
        )
        self.assertEqual(
            fts_protocol.build_command("polarization_mode", {"target": "ul", "value": "triggered"}),
            "set ul polarization controller mode triggered",
        )
        with self.assertRaisesRegex(ValueError, "10 and 2000"):
            fts_protocol.build_command("downlink_distance", {"target": "port1", "value": 5000})
        with self.assertRaisesRegex(ValueError, "194392.6 and 194405.6"):
            fts_protocol.build_command("laser_central_frequency", {"value": 194500})
        with self.assertRaisesRegex(ValueError, "no newlines"):
            fts_protocol.build_command("description", {"target": "port1", "value": "ok\nreboot"})

    def test_status_parser_recognizes_modular_port_types_and_metrics(self):
        output = """
Uplink
Description: Direction 1 -> Direction 2
State: LOCKED
Estimated Optical Power: -52 dBm
Low Frequency Noise: 10
High Frequency Noise: 13
Port1
Description: Direction 1 -> Direction 5
Type: Downlink
State: LOCKED
Estimated Optical Power: -53 dBm
Low Frequency Noise: 12
High Frequency Noise: 24
Jitter: 8 %
Port3
Type: Feedback Link
State: UNLOCKED
Port5
UNEQUIPPED
"""
        result = fts_protocol.parse_show_status(output, state.empty_fts_ls_status())

        self.assertEqual(result["uplink"]["optical_power"], -52)
        self.assertEqual(result["uplink"]["connectors"], ["O", "BN", "BNA"])
        self.assertEqual(result["ports"][0]["type"], "Downlink")
        self.assertEqual(result["ports"][0]["connectors"], ["O", "BN", "TR"])
        self.assertEqual(result["ports"][0]["jitter"], 8)
        self.assertEqual(result["ports"][2]["state"], "UNLOCKED")
        self.assertEqual(result["ports"][4]["connectors"], [])

    def test_detailed_output_maps_values_used_by_live_view(self):
        status = state.empty_fts_ls_status()
        fts_protocol.apply_detailed_output(
            status,
            "port1",
            """
Type: Downlink
State: LOCKED
Equivalent Distance: 30 km
Additional Gain Set: 12 dB
Noise Cancellation Loop State: LOCKED
""",
        )

        port = status["ports"][0]
        self.assertEqual(port["distance_km"], 30)
        self.assertEqual(port["additional_gain_db"], 12)
        self.assertEqual(port["state"], "LOCKED")

    def test_firmware_aliases_do_not_escape_the_protocol_adapter(self):
        status = state.empty_fts_ls_status()
        fts_protocol.apply_detailed_output(
            status,
            "tec",
            """
Status: ON
Temperature Set: 24.5 C
Temperature Read: 24.2 C
Power Usage: 31 %
""",
        )
        fts_protocol.apply_detailed_output(
            status,
            "laser",
            "Current Frequency: 194400.1 GHz",
        )

        self.assertEqual(
            status["tec"],
            {
                "state": "ON",
                "temperature_set_c": 24.5,
                "temperature_read_c": 24.2,
                "power_usage_percent": 31.0,
            },
        )
        self.assertEqual(status["laser"]["optical_frequency"], 194400.1)
        self.assertNotIn("temperature_read", status["tec"])
        self.assertNotIn("current_frequency", status["laser"])

    def test_status_text_is_preserved_without_alarm_interpretation(self):
        status = state.empty_fts_ls_status()
        fts_protocol.apply_detailed_output(status, "laser", "Status: warming up")

        self.assertEqual(status["laser"]["state"], "WARMING UP")


if __name__ == "__main__":
    unittest.main()
