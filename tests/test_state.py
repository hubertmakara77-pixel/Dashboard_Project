import json
import pathlib
import tempfile
import unittest
from unittest import mock

from app.core import config, state


class StateSecurityTests(unittest.TestCase):
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
