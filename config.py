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
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "my-super-token")
INFLUX_ORG = os.getenv("INFLUX_ORG", "agh")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "sensors")

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

AUDIT_LOG_FILE = os.getenv("AUDIT_LOG_FILE", "logs/audit.log")
