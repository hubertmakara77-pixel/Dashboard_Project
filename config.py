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

DEVICE_NAME = os.getenv("DEVICE_NAME", "optical_amp_1")

INFLUX_ENABLED = _env_bool("INFLUX_ENABLED", True)

INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUX_ORG", "agh")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "sensors")

INITIAL_ADMIN_PASSWORD = os.getenv("INITIAL_ADMIN_PASSWORD", "")
LOGIN_MAX_ATTEMPTS = _env_int("LOGIN_MAX_ATTEMPTS", 5)
LOGIN_WINDOW_SECONDS = _env_int("LOGIN_WINDOW_SECONDS", 300)
SESSION_MAX_AGE_SECONDS = _env_int("SESSION_MAX_AGE_SECONDS", 60 * 60 * 12)
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", False)
TRUST_PROXY_HEADERS = _env_bool("TRUST_PROXY_HEADERS", False)

MEASUREMENT_NAME = os.getenv("MEASUREMENT_NAME", "optical_amp_status")
SETPOINT_MEASUREMENT_NAME = os.getenv(
    "SETPOINT_MEASUREMENT_NAME",
    "optical_amp_setpoint",
)

HISTORY_MEMORY_LIMIT = _env_int("HISTORY_MEMORY_LIMIT", 10000)

PERSISTED_STATE_FILE = os.getenv("PERSISTED_STATE_FILE", "persisted_state.json")

SYSLOG_ENABLED = _env_bool("SYSLOG_ENABLED", True)
SYSLOG_HOST = os.getenv("SYSLOG_HOST", "127.0.0.1")
SYSLOG_PORT = _env_int("SYSLOG_PORT", 514)
SYSLOG_APP_NAME = os.getenv("SYSLOG_APP_NAME", "amp-dashboard")
SYSLOG_FACILITY = _env_int("SYSLOG_FACILITY", 16)
SYSLOG_TIMEZONE = os.getenv("SYSLOG_TIMEZONE", "Europe/Warsaw")

# AUDIT_LOG_FILE pozostaje jako zgodny wstecznie fallback dla starszych wdrozen.
SYSLOG_LOG_FILE = os.getenv("SYSLOG_LOG_FILE") or os.getenv("AUDIT_LOG_FILE") or "logs/syslog.log"

SNMP_PORT = _env_int("SNMP_PORT", 1161)
SNMP_COMMUNITY = os.getenv("SNMP_COMMUNITY", "")

# Główny Urząd Miar - krajowy serwer czasu (NTP/SNTP)
NTP_SERVER = os.getenv("NTP_SERVER", "tempus1.gum.gov.pl")
NTP_SERVER_FALLBACK_IP = os.getenv("NTP_SERVER_FALLBACK_IP", "194.146.251.100")
NTP_PORT = _env_int("NTP_PORT", 123)
NTP_TIMEOUT_SECONDS = _env_int("NTP_TIMEOUT_SECONDS", 3)
NTP_CACHE_SECONDS = _env_int("NTP_CACHE_SECONDS", 15)

RADIUS_SERVER = os.getenv("RADIUS_SERVER", "radius")
RADIUS_PORT = _env_int("RADIUS_PORT", 1812)
RADIUS_SECRET = os.getenv("RADIUS_SECRET", "")
RADIUS_TIMEOUT_SECONDS = _env_int("RADIUS_TIMEOUT_SECONDS", 3)
RADIUS_RETRIES = _env_int("RADIUS_RETRIES", 1)
RADIUS_NAS_IDENTIFIER = os.getenv("RADIUS_NAS_IDENTIFIER", "amp-dashboard")
