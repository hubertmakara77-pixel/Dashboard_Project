import os


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


SERIAL_PORT = os.getenv("SERIAL_PORT", "COM6")
SERIAL_BAUDRATE = _env_int("SERIAL_BAUDRATE", 9600)

DEVICE_NAME = os.getenv("DEVICE_NAME", "unconfigured-device")

DATABASE_FILE = os.getenv("DATABASE_FILE", "data/measurements.db")
DATABASE_MAX_RECORDS = max(0, _env_int("DATABASE_MAX_RECORDS", 0))
HISTORY_MAX_POINTS = max(100, _env_int("HISTORY_MAX_POINTS", 2000))

LOGIN_MAX_ATTEMPTS = _env_int("LOGIN_MAX_ATTEMPTS", 5)
LOGIN_WINDOW_SECONDS = _env_int("LOGIN_WINDOW_SECONDS", 300)
SESSION_MAX_AGE_SECONDS = _env_int("SESSION_MAX_AGE_SECONDS", 60 * 60 * 12)
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", False)
TRUST_PROXY_HEADERS = _env_bool("TRUST_PROXY_HEADERS", False)

PERSISTED_STATE_FILE = os.getenv("PERSISTED_STATE_FILE", "persisted_state.json")

SYSLOG_ENABLED = _env_bool("SYSLOG_ENABLED", True)
SYSLOG_HOST = os.getenv("SYSLOG_HOST", "127.0.0.1")
SYSLOG_PORT = _env_int("SYSLOG_PORT", 514)
SYSLOG_APP_NAME = os.getenv("SYSLOG_APP_NAME", "amp-dashboard")
SYSLOG_FACILITY = _env_int("SYSLOG_FACILITY", 16)
SYSLOG_TIMEZONE = os.getenv("SYSLOG_TIMEZONE", "Europe/Warsaw")
SYSLOG_HEARTBEAT_SECONDS = max(0, _env_int("SYSLOG_HEARTBEAT_SECONDS", 300))

SYSLOG_EXPORT_FILE = os.getenv("SYSLOG_EXPORT_FILE", "/var/log/amp-dashboard/amp-dashboard.log")
REMOTE_SYSLOG_ENABLED = _env_bool("REMOTE_SYSLOG_ENABLED", False)
REMOTE_SYSLOG_HOST = os.getenv("REMOTE_SYSLOG_HOST", "")
REMOTE_SYSLOG_PORT = _env_int("REMOTE_SYSLOG_PORT", 514)
REMOTE_SYSLOG_PROTOCOL = os.getenv("REMOTE_SYSLOG_PROTOCOL", "tcp")

SNMP_PORT = _env_int("SNMP_PORT", 1161)
SNMP_COMMUNITY = os.getenv("SNMP_COMMUNITY", "")

# Główny Urząd Miar - krajowy serwer czasu (NTP/SNTP)
NTP_SERVER = os.getenv("NTP_SERVER", "tempus1.gum.gov.pl")
NTP_SERVER_FALLBACK_IP = os.getenv("NTP_SERVER_FALLBACK_IP", "194.146.251.100")
NTP_PORT = _env_int("NTP_PORT", 123)
NTP_TIMEOUT_SECONDS = _env_int("NTP_TIMEOUT_SECONDS", 3)
NTP_CACHE_SECONDS = _env_int("NTP_CACHE_SECONDS", 15)

RADIUS_SERVER = os.getenv("RADIUS_SERVER", "")
RADIUS_PORT = _env_int("RADIUS_PORT", 1812)
RADIUS_SECRET = os.getenv("RADIUS_SECRET", "")
RADIUS_TIMEOUT_SECONDS = _env_int("RADIUS_TIMEOUT_SECONDS", 3)
RADIUS_RETRIES = _env_int("RADIUS_RETRIES", 1)
RADIUS_NAS_IDENTIFIER = os.getenv("RADIUS_NAS_IDENTIFIER", DEVICE_NAME)
