import json
import pathlib
import tempfile
import unittest
from unittest import mock

from app.core import config, state


class StateSecurityTests(unittest.TestCase):
    def test_zero_database_limit_means_unlimited(self):
        settings = state.merge_service_settings({"database_max_records": 0})
        self.assertEqual(settings["database_max_records"], 0)

    def test_temperature_thresholds_are_added_to_existing_settings(self):
        settings = state.merge_dashboard_settings({
            "warn_limits": {
                "PiA": {"min": -20.0, "max": 5.0},
            },
        })

        self.assertEqual(settings["warn_limits"]["PiA"], {"min": -20.0, "max": 5.0})
        self.assertEqual(
            settings["warn_limits"]["temperature"],
            {"min": None, "max": None},
        )

    def test_unsafe_persisted_dashboard_settings_fall_back_to_defaults(self):
        settings = state.merge_dashboard_settings({
            "gain_tolerance": -1,
            "warn_limits": {
                "temperature": {"min": 100.0, "max": 10.0},
            },
        })
        self.assertEqual(settings, state.DEFAULT_DASHBOARD_SETTINGS)

    def test_unsafe_persisted_gain_set_is_not_restored_to_device(self):
        self.assertEqual(state.merge_last_known_gain_set(float("nan")), 15.0)
        self.assertEqual(state.merge_last_known_gain_set(1000), 15.0)

    def test_fresh_install_creates_admin_authorization_without_password(self):
        users = state.merge_access_users(None)
        self.assertEqual(users[0]["username"], "admin")
        self.assertEqual(users[0]["role"], "Administrator")
        self.assertNotIn("password_hash", users[0])
        self.assertNotIn("password_salt", users[0])

    def test_legacy_password_hashes_are_removed(self):
        users = state.merge_access_users([{
            "username": "operator",
            "role": "Operator",
            "active": True,
            "password_hash": "legacy-hash",
            "password_salt": "legacy-salt",
        }])
        self.assertEqual(users, [{
            "username": "operator",
            "role": "Operator",
            "active": True,
        }])

    def test_persisted_state_is_written_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "state.json"
            with mock.patch.object(config, "PERSISTED_STATE_FILE", str(path)):
                state.save_persisted_state()
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("access_users", payload)
            self.assertNotIn("password_hash", json.dumps(payload))
            self.assertNotIn("password_salt", json.dumps(payload))
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
