"""Reset the password of an existing dashboard account.

Run this inside the running container, e.g.:

    docker compose --profile dashboard exec app python reset_admin_password.py admin

It will prompt for the new password (hidden input), hash it the same way
state.py does, and rewrite only that user's password_hash/password_salt in
persisted_state.json. Everything else (dashboard_settings, snmp_settings,
other users, last_known_gain_set) is left untouched.
"""

import argparse
import getpass
import sys

import state


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset a dashboard account password")
    parser.add_argument("username", nargs="?", default="admin")
    args = parser.parse_args()

    target = args.username.strip()

    user = next((u for u in state.access_users if u["username"] == target), None)
    if user is None:
        print(f"No user named '{target}' found in persisted_state.json.")
        print("Existing users:", ", ".join(u["username"] for u in state.access_users) or "(none)")
        return 1

    password = getpass.getpass(f"New password for '{target}' (min 12 chars): ")
    if len(password) < 12:
        print("Password must be at least 12 characters.")
        return 1

    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.")
        return 1

    password_hash, password_salt = state.hash_password(password)
    user["password_hash"] = password_hash
    user["password_salt"] = password_salt
    user["active"] = True

    state.save_persisted_state()
    print(f"Password for '{target}' updated in {state.config.PERSISTED_STATE_FILE}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())