import math
import unittest

from app.core.validation import validate_gain_set, validated_dashboard_settings

SETTINGS = {
    "gain_tolerance": 1.0,
    "warn_limits": {
        "temperature": {"min": 0.0, "max": 80.0},
        "PiA": {"min": None, "max": 10.0},
    },
}


class ValidationTests(unittest.TestCase):
    def test_gain_set_must_be_finite_and_in_configured_range(self):
        self.assertEqual(validate_gain_set(15, -100, 100), 15.0)
        for value in (math.nan, math.inf, -math.inf, 101, 10**10000):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_gain_set(value, -100, 100)

    def test_tolerance_cannot_be_negative_or_non_finite(self):
        for value in (-0.1, math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validated_dashboard_settings(SETTINGS, value, None)

    def test_rejects_reversed_limits_after_partial_update(self):
        with self.assertRaisesRegex(ValueError, "MIN threshold must be lower"):
            validated_dashboard_settings(
                SETTINGS,
                None,
                {"temperature": {"min": 90}},
            )

    def test_rejects_unknown_fields_and_limit_keys(self):
        with self.assertRaisesRegex(ValueError, "Unknown warning fields"):
            validated_dashboard_settings(
                SETTINGS,
                None,
                {"voltage": {"min": 0}},
            )
        with self.assertRaisesRegex(ValueError, "unknown limit keys"):
            validated_dashboard_settings(
                SETTINGS,
                None,
                {"temperature": {"average": 20}},
            )

    def test_validation_does_not_mutate_current_settings_on_error(self):
        before = {
            "gain_tolerance": SETTINGS["gain_tolerance"],
            "warn_limits": {
                field: dict(limits) for field, limits in SETTINGS["warn_limits"].items()
            },
        }
        with self.assertRaises(ValueError):
            validated_dashboard_settings(
                SETTINGS,
                None,
                {"temperature": {"min": 90}},
            )
        self.assertEqual(SETTINGS, before)


if __name__ == "__main__":
    unittest.main()
