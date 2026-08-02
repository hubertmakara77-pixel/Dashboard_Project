import unittest

from app.core import state
from app.services import fts_ls


class FtsLsTests(unittest.TestCase):
    def test_documented_commands_are_built_with_validation(self):
        self.assertEqual(
            fts_ls.build_command(
                "laser_central_frequency", {"value": 194397.7}
            ),
            "set laser central frequency 194397.7",
        )
        self.assertEqual(
            fts_ls.build_command(
                "laser_central_frequency", {"value": 194400}
            ),
            "set laser central frequency 194400",
        )
        self.assertEqual(
            fts_ls.build_command(
                "downlink_distance", {"target": "P2", "value": 500}
            ),
            "set port2 downlink distance 500",
        )
        self.assertEqual(
            fts_ls.build_command(
                "polarization_mode", {"target": "ul", "value": "triggered"}
            ),
            "set ul polarization controller mode triggered",
        )
        with self.assertRaisesRegex(ValueError, "10 and 2000"):
            fts_ls.build_command(
                "downlink_distance", {"target": "port1", "value": 5000}
            )
        with self.assertRaisesRegex(ValueError, "194392.6 and 194405.6"):
            fts_ls.build_command(
                "laser_central_frequency", {"value": 194500}
            )
        with self.assertRaisesRegex(ValueError, "no newlines"):
            fts_ls.build_command(
                "description", {"target": "port1", "value": "ok\nreboot"}
            )

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
        result = fts_ls.parse_show_status(output, state.empty_fts_ls_status())

        self.assertEqual(result["uplink"]["optical_power"], -52)
        self.assertEqual(result["uplink"]["connectors"], ["O", "BN", "BNA"])
        self.assertEqual(result["ports"][0]["type"], "Downlink")
        self.assertEqual(result["ports"][0]["connectors"], ["O", "BN", "TR"])
        self.assertEqual(result["ports"][0]["jitter"], 8)
        self.assertEqual(result["ports"][2]["state"], "UNLOCKED")
        self.assertEqual(result["ports"][4]["connectors"], [])

    def test_detailed_output_maps_values_used_by_live_view(self):
        status = state.empty_fts_ls_status()
        fts_ls.apply_detailed_output(
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

    def test_manual_quality_indicators_create_alarm_candidates(self):
        status = state.empty_fts_ls_status()
        status["ports"][0].update({
            "state": "UNLOCKED",
            "noise_lf": 101,
            "jitter": 51,
            "optical_power_display": "LOW",
        })
        warnings = fts_ls._warning_candidates(
            status, "2026-08-02T12:00:00+00:00"
        )

        self.assertIn(("P1", "lock_state"), warnings)
        self.assertIn(("P1", "noise_lf"), warnings)
        self.assertIn(("P1", "jitter"), warnings)
        self.assertIn(("P1", "optical_power"), warnings)


if __name__ == "__main__":
    unittest.main()
