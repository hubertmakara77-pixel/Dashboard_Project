import collections
import base64
import hashlib
import json
import pathlib
import secrets
import threading

import config


persist_lock = threading.Lock()


DEFAULT_DASHBOARD_SETTINGS = {
    "gain_tolerance": 0.25,
    "warn_limits": {
        "PiA": {"min": None, "max": None},
        "PoA": {"min": None, "max": None},
        "PiB": {"min": None, "max": None},
        "PoB": {"min": None, "max": None},
    },
}

DEFAULT_SNMP_SETTINGS = {
    "enabled": False,
    "port": config.SNMP_PORT,
    "community": config.SNMP_COMMUNITY,
    "trap_host": "127.0.0.1",
    "trap_port": 162,
}

def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if salt is None:
        salt_bytes = secrets.token_bytes(16)
        salt = base64.b64encode(salt_bytes).decode("ascii")
    else:
        salt_bytes = base64.b64decode(salt.encode("ascii"))

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        120_000,
    )

    return base64.b64encode(digest).decode("ascii"), salt


def verify_password(password: str, password_hash: str, password_salt: str) -> bool:
    if not password_hash or not password_salt:
        return False

    try:
        expected_hash, _ = hash_password(password, password_salt)
    except (ValueError, TypeError):
        return False

    return secrets.compare_digest(expected_hash, password_hash)


def load_persisted_state() -> dict:
    path = pathlib.Path(config.PERSISTED_STATE_FILE)

    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def merge_dashboard_settings(saved_settings: dict | None) -> dict:
    settings = json.loads(json.dumps(DEFAULT_DASHBOARD_SETTINGS))

    if not isinstance(saved_settings, dict):
        return settings

    if "gain_tolerance" in saved_settings:
        settings["gain_tolerance"] = float(saved_settings["gain_tolerance"])

    saved_limits = saved_settings.get("warn_limits")
    if isinstance(saved_limits, dict):
        for field, limits in saved_limits.items():
            if field not in settings["warn_limits"] or not isinstance(limits, dict):
                continue

            for side in ("min", "max"):
                if side in limits:
                    value = limits[side]
                    settings["warn_limits"][field][side] = None if value is None else float(value)

    return settings


def access_user_public(user: dict) -> dict:
    return {
        "username": user["username"],
        "role": user["role"],
        "active": bool(user["active"]),
        "password_set": bool(user.get("password_hash")),
    }


def merge_access_users(saved_users: list[dict] | None) -> list[dict]:
    merged_users = []
    seen_usernames = set()

    for user in saved_users if isinstance(saved_users, list) else []:
        if not isinstance(user, dict):
            continue

        username = str(user.get("username", "")).strip()
        if not username or username in seen_usernames:
            continue

        merged_users.append({
            "username": username,
            "role": str(user.get("role", "Operator")).strip() or "Operator",
            "active": bool(user.get("active", True)),
            "password_hash": str(user.get("password_hash", "")),
            "password_salt": str(user.get("password_salt", "")),
        })
        seen_usernames.add(username)

    if merged_users:
        return merged_users

    if len(config.INITIAL_ADMIN_PASSWORD) < 12:
        raise RuntimeError(
            "A fresh installation requires INITIAL_ADMIN_PASSWORD with at least 12 characters. "
            "Run install_dashboard.sh or configure the environment."
        )

    password_hash, password_salt = hash_password(config.INITIAL_ADMIN_PASSWORD)
    return [{
        "username": "admin",
        "role": "Administrator",
        "active": True,
        "password_hash": password_hash,
        "password_salt": password_salt,
    }]


def merge_snmp_settings(saved_settings: dict | None) -> dict:
    settings = DEFAULT_SNMP_SETTINGS.copy()
    if isinstance(saved_settings, dict):
        settings.update({key: saved_settings[key] for key in settings if key in saved_settings})
    settings["port"] = config.SNMP_PORT
    if settings.get("community") in {"", "public"}:
        settings["community"] = config.SNMP_COMMUNITY
    return settings


persisted_state = load_persisted_state()


def save_persisted_state() -> None:
    path = pathlib.Path(config.PERSISTED_STATE_FILE)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "last_known_gain_set": float(last_known_gain_set),
        "dashboard_settings": dashboard_settings,
        "access_users": access_users,
        "snmp_settings": snmp_settings,
    }
    with persist_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary_path.chmod(0o600)
        temporary_path.replace(path)


def save_persisted_gain_set(gain_set: float) -> None:
    global last_known_gain_set
    last_known_gain_set = float(gain_set)
    save_persisted_state()


def save_persisted_dashboard_settings() -> None:
    save_persisted_state()


def save_persisted_access_users() -> None:
    save_persisted_state()


latest_data = {}
latest_snmp_data = {}
serial_connected = False
serial_error = None
last_update = None
last_command_response = None
last_known_gain_set = float(persisted_state.get("last_known_gain_set", 15.0))

serial_port = None

state_lock = threading.Lock()
serial_lock = threading.Lock()
stop_event = threading.Event()

history_buffer = collections.deque(maxlen=config.HISTORY_MEMORY_LIMIT)
error_buffer = collections.deque(maxlen=500)
active_warning_keys = set()
auth_sessions = {}
login_failures = {}

dashboard_settings = merge_dashboard_settings(persisted_state.get("dashboard_settings"))
access_users = merge_access_users(persisted_state.get("access_users"))
snmp_settings = merge_snmp_settings(persisted_state.get("snmp_settings"))
