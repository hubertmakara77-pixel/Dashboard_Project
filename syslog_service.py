import datetime
import pathlib
import socket
import threading
import zoneinfo

import config


FACILITY_LOCAL0 = config.SYSLOG_FACILITY
SEVERITY_WARNING = 4
SEVERITY_INFO = 6
syslog_log_lock = threading.Lock()


def local_now() -> datetime.datetime:
    try:
        timezone = zoneinfo.ZoneInfo(config.SYSLOG_TIMEZONE)
    except zoneinfo.ZoneInfoNotFoundError:
        timezone = datetime.timezone.utc
    return datetime.datetime.now(timezone)


def append_syslog_log(message: str) -> None:
    if not config.SYSLOG_LOG_FILE:
        return

    path = pathlib.Path(config.SYSLOG_LOG_FILE)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with syslog_log_lock:
            with path.open("a", encoding="utf-8") as file:
                file.write(message + "\n")
    except OSError as error:
        print(f"Syslog file write failed: {error}")


def send_syslog(message: str, severity: int) -> None:
    if not config.SYSLOG_ENABLED:
        return

    priority = FACILITY_LOCAL0 * 8 + severity
    timestamp = local_now().strftime("%b %d %H:%M:%S")
    hostname = socket.gethostname()
    payload = f"<{priority}>{timestamp} {hostname} {config.SYSLOG_APP_NAME}: {message}"

    # Lokalna kopia pozwala pobrac pelny syslog aplikacji nawet wtedy, gdy
    # zewnetrzny odbiornik UDP jest chwilowo niedostepny.
    append_syslog_log(payload)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload.encode("utf-8"), (config.SYSLOG_HOST, config.SYSLOG_PORT))
    except OSError as error:
        print(f"Syslog send failed: {error}")


def send_warning(message: str) -> None:
    send_syslog(message, SEVERITY_WARNING)


def get_syslog_log_path() -> pathlib.Path:
    return pathlib.Path(config.SYSLOG_LOG_FILE)


def get_audit_log_path() -> pathlib.Path:
    """Zgodny wstecznie alias dla starszych wywolan."""
    return get_syslog_log_path()


def send_audit(action: str, username: str, ip_address: str, details: str = "") -> None:
    timestamp = local_now().isoformat(timespec="seconds")
    detail_text = f"; details={details}" if details else ""
    message = f"audit timestamp={timestamp}; user={username}; ip={ip_address}; action={action}{detail_text}"

    send_syslog(
        message,
        SEVERITY_INFO,
    )
