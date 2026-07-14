import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("INITIAL_ADMIN_PASSWORD", "test-bootstrap-password")

import config
import state


class StateSecurityTests(unittest.TestCase):
    def test_fresh_install_requires_strong_initial_password(self):
        with mock.patch.object(config, "INITIAL_ADMIN_PASSWORD", "short"):
            with self.assertRaisesRegex(RuntimeError, "at least 12"):
                state.merge_access_users(None)

    def test_bootstrap_password_is_hashed(self):
        with mock.patch.object(config, "INITIAL_ADMIN_PASSWORD", "a-secure-bootstrap-password"):
            users = state.merge_access_users(None)
        self.assertEqual(users[0]["username"], "admin")
        self.assertNotEqual(users[0]["password_hash"], "a-secure-bootstrap-password")
        self.assertTrue(state.verify_password("a-secure-bootstrap-password", users[0]["password_hash"], users[0]["password_salt"]))

    def test_persisted_state_is_written_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "state.json"
            with mock.patch.object(config, "PERSISTED_STATE_FILE", str(path)):
                state.save_persisted_state()
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("access_users", payload)
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
