import unittest

from app.protocols import amplifier


class AmplifierProtocolTests(unittest.TestCase):
    def test_measurement_labels_are_normalized_at_protocol_boundary(self):
        result = amplifier.parse_line(
            "#M:PiA:-12.3;PoA:2.7;Temperature:34.2;seq_nr:18;unused:-999*"
        )

        self.assertEqual(
            result,
            {
                "PiA": -12.3,
                "PoA": 2.7,
                "temperature": 34.2,
                "seq_nr": 18.0,
            },
        )
        self.assertNotIn("Temperature", result)

    def test_command_response_uses_the_same_canonical_names(self):
        self.assertEqual(
            amplifier.parse_line("status=OK;T=40.5;gain_set=15.25"),
            {"status": "OK", "temperature": 40.5, "gain_set": 15.25},
        )

    def test_gain_command_format_is_owned_by_the_adapter(self):
        self.assertEqual(amplifier.build_gain_command(15.25), b"SET_GAIN=15.25\n")


if __name__ == "__main__":
    unittest.main()
